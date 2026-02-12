import sys
import os
import re
import json
import math
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QRadioButton, 
                            QPushButton, QFileDialog, QMessageBox, QProgressBar,
                            QButtonGroup, QGridLayout, QGroupBox, QSpinBox, QCheckBox,
                            QSizePolicy)
from PyQt6.QtGui import QPainter
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtGui import QPalette, QBrush, QPixmap, QColor
import yt_dlp

# Autumn Harvest palette (7 color bars)
COLOR_PALETTE = ["#F2E4CF", "#EAD6B8", "#D7B680", "#B07D52", "#8B593D", "#6A3F2C", "#49201E"]


class ColorStripe(QWidget):
    """Paints a horizontal stripe comprised of palette color bars."""
    def __init__(self, colors, parent=None):
        super().__init__(parent)
        self.colors = colors or []
        self.setMinimumHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        painter = QPainter(self)
        w = self.width()
        h = self.height()
        if not self.colors:
            return
        bar_w = max(1, w // len(self.colors))
        for i, color in enumerate(self.colors):
            painter.fillRect(i * bar_w, 0, bar_w, h, QColor(color))
        painter.end()


# ========== Worker Thread ==========

class YoutubeExtractorThread(QThread):
    progress_signal = pyqtSignal(int, int)   # current, total
    finished_signal = pyqtSignal(list)       # list of URLs
    error_signal = pyqtSignal(str)

    def __init__(self, channel_input, extract_type, video_count=None,
                 use_api=False, api_key=None,
                 quick_popular=False, cookies_path=None, workers=8):
        super().__init__()
        self.channel_input = channel_input.strip()
        self.extract_type = extract_type
        self.video_count = int(video_count) if video_count else None
        self.use_api = use_api
        self.api_key = (api_key or "").strip()
        self.quick_popular = quick_popular
        self.cookies_path = cookies_path
        self.workers = max(1, int(workers))

    # ---------- yt-dlp helpers ----------
    def _normalize_to_channel_url(self, raw):
        if raw.startswith("http"):
            return raw.rstrip("/")
        if raw.startswith("@"):
            return f"https://www.youtube.com/{raw}"
        return f"https://www.youtube.com/channel/{raw}"

    def _extract_uc_from_input(self):
        """Lấy UC… từ UC/@handle/URL bằng yt-dlp (ổn định, nhanh)."""
        raw = self.channel_input

        if raw.startswith("UC"):
            return raw

        m = re.search(r"/channel/(UC[0-9A-Za-z_-]+)", raw)
        if m:
            return m.group(1)

        probe_opts = {
            "quiet": True,
            "extract_flat": True,
            "ignoreerrors": True,
        }
        if self.cookies_path:
            probe_opts["cookies"] = self.cookies_path

        url = self._normalize_to_channel_url(raw)
        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        uc = None
        if isinstance(info, dict):
            uc = info.get("channel_id") or info.get("uploader_id") or info.get("id")
            if not (uc and uc.startswith("UC")):
                entries = info.get("entries") or []
                if entries:
                    first = entries[0] or {}
                    uc = first.get("channel_id") or first.get("uploader_id")
        if not (uc and uc.startswith("UC")):
            raise RuntimeError("Không xác định được Channel ID (UC…) từ đầu vào.")
        return uc

    def _uploads_playlist_from_uc(self, uc):
        return f"UU{uc[2:]}"

    def _yt_opts(self, flat=True):
        opts = {
            "quiet": True,
            "ignoreerrors": True,
            "extract_flat": bool(flat),
        }
        if self.cookies_path:
            opts["cookies"] = self.cookies_path
        return opts

    def _fetch_upload_entries_flat(self, uploads_playlist_id):
        """Lấy toàn bộ entries từ uploads playlist (flat, có phân trang)."""
        url = f"https://www.youtube.com/playlist?list={uploads_playlist_id}"
        with yt_dlp.YoutubeDL(self._yt_opts(flat=True)) as ydl:
            info = ydl.extract_info(url, download=False)
        return info.get("entries") or []

    # ---------- Popular modes ----------
    def _collect_popular_shelf_quick(self, base_channel_url, top_n):
        """Cách nhanh: tab Popular, thường chỉ ~30–60 video."""
        shelf_url = f"{base_channel_url}/videos?view=0&sort=p&flow=grid"
        with yt_dlp.YoutubeDL(self._yt_opts(flat=True)) as ydl:
            info = ydl.extract_info(shelf_url, download=False)
        entries = info.get("entries") or []
        total = min(top_n, len(entries)) if top_n else len(entries)
        urls = []
        for i, e in enumerate(entries[:total], start=1):
            vid = e.get("id")
            if vid:
                urls.append(f"https://www.youtube.com/watch?v={vid}")
            self.progress_signal.emit(i, total)
        return urls

    def _fetch_views_single(self, vid):
        """Lấy view_count cho 1 video bằng yt-dlp (non-flat)."""
        try:
            with yt_dlp.YoutubeDL(self._yt_opts(flat=False)) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            return int(info.get("view_count") or 0)
        except Exception:
            return 0

    def _collect_popular_deep_concurrent(self, uploads_playlist_id, top_n):
        """Chính xác: quét hết uploads, lấy view_count song song và sort."""
        entries = self._fetch_upload_entries_flat(uploads_playlist_id)
        ids = [e.get("id") for e in entries if e and e.get("id")]
        total = len(ids)
        if total == 0:
            return []

        results = []
        done = 0
        self.progress_signal.emit(0, total)

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(self._fetch_views_single, vid): vid for vid in ids}
            for fut in as_completed(futs):
                vid = futs[fut]
                views = 0
                try:
                    views = int(fut.result() or 0)
                except Exception:
                    views = 0
                results.append((views, vid))
                done += 1
                self.progress_signal.emit(done, total)

        results.sort(key=lambda x: x[0], reverse=True)
        chosen = results if (not top_n or top_n <= 0) else results[:top_n]
        return [f"https://www.youtube.com/watch?v={vid}" for _, vid in chosen]

    # ---------- YouTube Data API (fast & full) ----------
    def _http_get_json(self, url, params):
        q = urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{url}?{q}") as resp:
            data = resp.read()
        return json.loads(data.decode("utf-8"))

    def _collect_popular_via_api(self, uc, top_n):
        """Dùng YouTube Data API v3: rất nhanh & đủ. Cần API key."""
        if not self.api_key:
            raise RuntimeError("Thiếu API key cho YouTube Data API.")

        # Lấy uploads playlist ID
        ch = self._http_get_json(
            "https://www.googleapis.com/youtube/v3/channels",
            {"part": "contentDetails", "id": uc, "key": self.api_key}
        )
        items = ch.get("items") or []
        if not items:
            raise RuntimeError("API không tìm thấy kênh.")
        uploads_pid = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # Lấy toàn bộ videoId từ uploads (50/req)
        video_ids = []
        page_token = None
        total_scan_reported = 0
        while True:
            params = {
                "part": "contentDetails",
                "playlistId": uploads_pid,
                "maxResults": 50,
                "key": self.api_key
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._http_get_json("https://www.googleapis.com/youtube/v3/playlistItems", params)
            items = data.get("items") or []
            for it in items:
                vid = it["contentDetails"].get("videoId")
                if vid:
                    video_ids.append(vid)
            page_token = data.get("nextPageToken")

            # cập nhật tiến trình theo số item đã gom
            total_scan_reported += len(items)
            self.progress_signal.emit(total_scan_reported, max(total_scan_reported, 1))

            if not page_token:
                break

        if not video_ids:
            return []

        # Lấy statistics theo lô 50 id/lần
        scored = []
        total = len(video_ids)
        done = 0
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            stats = self._http_get_json(
                "https://www.googleapis.com/youtube/v3/videos",
                {"part": "statistics", "id": ",".join(batch), "key": self.api_key}
            )
            for it in stats.get("items", []):
                vid = it.get("id")
                views = int(it.get("statistics", {}).get("viewCount", 0))
                if vid:
                    scored.append((views, vid))
            done = min(i + 50, total)
            self.progress_signal.emit(done, total)

        scored.sort(key=lambda x: x[0], reverse=True)
        chosen = scored if (not top_n or top_n <= 0) else scored[:top_n]
        return [f"https://www.youtube.com/watch?v={vid}" for _, vid in chosen]

    # ---------- Main run ----------
    def run(self):
        try:
            if self.extract_type not in ("all", "recent", "popular"):
                raise RuntimeError("Kiểu lấy video không hợp lệ.")

            # Luôn resolve UC id 1 lần
            uc = self._extract_uc_from_input()
            uploads_pid = self._uploads_playlist_from_uc(uc)

            # Popular
            if self.extract_type == "popular":
                top_n = max(1, int(self.video_count or 50))

                # Ưu tiên API nếu bật
                if self.use_api:
                    urls = self._collect_popular_via_api(uc, top_n)
                    self.finished_signal.emit(urls)
                    return

                # Nếu chọn nhanh (shelf)
                if self.quick_popular:
                    base = self._normalize_to_channel_url(self.channel_input)
                    urls = self._collect_popular_shelf_quick(base, top_n)
                    self.finished_signal.emit(urls)
                    return

                # Mặc định: deep + đa luồng
                urls = self._collect_popular_deep_concurrent(uploads_pid, top_n)
                self.finished_signal.emit(urls)
                return

            # All / Recent dựa vào uploads (đầy đủ)
            entries = self._fetch_upload_entries_flat(uploads_pid)

            if self.extract_type == "all":
                total = len(entries)
                urls = []
                for i, e in enumerate(entries, start=1):
                    vid = e.get("id")
                    if vid:
                        urls.append(f"https://www.youtube.com/watch?v={vid}")
                    self.progress_signal.emit(i, total)
                self.finished_signal.emit(urls)
                return

            if self.extract_type == "recent":
                count = max(1, int(self.video_count or 1))
                total = min(count, len(entries))
                urls = []
                for i, e in enumerate(entries[:total], start=1):
                    vid = e.get("id")
                    if vid:
                        urls.append(f"https://www.youtube.com/watch?v={vid}")
                    self.progress_signal.emit(i, total)
                self.finished_signal.emit(urls)
                return

        except Exception as e:
            self.error_signal.emit(str(e))


# ========== Main Window ==========
class YoutubeUrlExtractor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Công Cụ Lấy URL Kênh YouTube")
        self.setMinimumSize(500, 690)

        self.video_urls = []
        self.cookies_path = None
        self.setup_ui()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Kết hợp với tên file ảnh
        image_path = os.path.join(current_dir, "cloud1.png")

        background = QPixmap(image_path)

        # 2. Scale it to the current window size
        scaled_background = background.scaled(
            central_widget.size(),  # Dùng central_widget.size() thay vì self.size()
            Qt.AspectRatioMode.KeepAspectRatioByExpanding, 
            Qt.TransformationMode.SmoothTransformation
        )

        # 3. Apply to the Palette của central_widget (KHÔNG PHẢI self)
        palette = central_widget.palette()
        palette.setBrush(QPalette.ColorRole.Window, QBrush(scaled_background))
        central_widget.setPalette(palette)
        central_widget.setAutoFillBackground(True)

        main_layout = QVBoxLayout(central_widget)
        # Palette stripe (UI refinement)
        try:
            color_stripe = ColorStripe(COLOR_PALETTE, central_widget)
            main_layout.addWidget(color_stripe)
        except Exception:
            pass
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        title_label = QLabel("CÔNG CỤ LẤY URL KÊNH YOUTUBE")
        title_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)

        # Thông tin kênh
        channel_group = QGroupBox("Thông tin kênh")
        channel_layout = QGridLayout(channel_group)
        channel_group.setStyleSheet("""
            QGroupBox {
                background-color: rgba(255, 255, 255, 210);
                border: 1px solid rgba(0, 0, 0, 25);
                border-radius: 12px;
                margin-top: 15px;
                color: #111;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
            }
        """)

# Thêm lề để nội dung bên trong không dính sát vào viền box
        channel_layout.setContentsMargins(15, 25, 15, 15)
        channel_layout.setSpacing(10)

        channel_id_label = QLabel("UID/Handle/URL kênh:")
        self.channel_id_input = QLineEdit()
        self.channel_id_input.setPlaceholderText("Nhập UC…, @handle, hoặc URL kênh (ví dụ: UCxxx…, @abc, https://...)",)
        self.channel_id_input.setStyleSheet("border: 1px solid black; border-radius: 4px; padding: 2px; color: black;")

        channel_layout.addWidget(channel_id_label, 0, 0)
        channel_layout.addWidget(self.channel_id_input, 0, 1)
        main_layout.addWidget(channel_group)

        # Lựa chọn kiểu lấy video
        extract_group = QGroupBox("Cách lấy video")
        extract_layout = QVBoxLayout(extract_group)
        self.extract_type_group = QButtonGroup(self)
        extract_group.setStyleSheet("""
            QGroupBox {
                background-color: rgba(255, 255, 255, 210);
                border: 1px solid rgba(0, 0, 0, 25);
                border-radius: 12px;
                margin-top: 15px;
                color: #111;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
            }
        """)

        self.all_videos_radio = QRadioButton("Toàn bộ video (Uploads)")
        self.popular_videos_radio = QRadioButton("Phổ biến nhất (sắp xếp theo view_count)")
        self.recent_videos_radio = QRadioButton("Gần đây nhất")

        self.extract_type_group.addButton(self.all_videos_radio, 0)
        self.extract_type_group.addButton(self.popular_videos_radio, 1)
        self.extract_type_group.addButton(self.recent_videos_radio, 2)
        self.all_videos_radio.setChecked(True)

        extract_layout.addWidget(self.all_videos_radio)

        pop_row = QHBoxLayout()
        pop_row.addWidget(self.popular_videos_radio)
        pop_row.addWidget(label := QLabel("Số lượng:"))
        self.popular_count = QSpinBox()
        self.popular_count.setRange(1, 100000)
        self.popular_count.setValue(100)
        self.popular_count.setStyleSheet("border: 1px solid black; border-radius: 4px; padding: 2px; color: black;")
        pop_row.addWidget(self.popular_count)
        pop_row.addStretch()
        extract_layout.addLayout(pop_row)

        recent_row = QHBoxLayout()
        recent_row.addWidget(self.recent_videos_radio)
        recent_row.addWidget(label := QLabel("Số lượng:"))
        self.recent_count = QSpinBox()
        self.recent_count.setRange(1, 100000)
        self.recent_count.setValue(200)
        self.recent_count.setStyleSheet("border: 1px solid black; border-radius: 4px; padding: 2px; color: black;")
        recent_row.addWidget(self.recent_count)
        recent_row.addStretch()
        extract_layout.addLayout(recent_row)

        main_layout.addWidget(extract_group)

        # Tăng tốc & Độ phủ
        accel_group = QGroupBox("Tăng tốc & Độ phủ (tùy chọn)")
        accel = QGridLayout(accel_group)
        accel_group.setStyleSheet("""
            QGroupBox {
                background-color: rgba(255, 255, 255, 210);
                border: 1px solid rgba(0, 0, 0, 25);
                border-radius: 12px;
                margin-top: 15px;
                color: #111;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
            }
        """)

        self.quick_popular_cb = QCheckBox("Phổ biến nhanh (≤ ~60 video từ tab Popular)")
        accel.addWidget(self.quick_popular_cb, 0, 0, 1, 2)

        accel.addWidget(QLabel("Số luồng (deep):"), 1, 0)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 64)
        self.workers_spin.setValue(8)
        self.workers_spin.setStyleSheet("border: 1px solid black; border-radius: 4px; padding: 2px; color: black;")
        accel.addWidget(self.workers_spin, 1, 1)

        self.cookies_cb = QCheckBox("Dùng cookies.txt (xử lý clip giới hạn tuổi/khu vực)")
        accel.addWidget(self.cookies_cb, 2, 0)
        self.cookies_path_edit = QLineEdit(); self.cookies_path_edit.setReadOnly(True)
        self.cookies_path_edit.setStyleSheet("border: 1px solid black; border-radius: 4px; padding: 2px; color: black;")
        self.cookies_browse_btn = QPushButton("Chọn…")
        self.cookies_browse_btn.clicked.connect(self.pick_cookies_file)
        row_cookies = QHBoxLayout()
        row_cookies.addWidget(self.cookies_path_edit); row_cookies.addWidget(self.cookies_browse_btn)
        accel.addLayout(row_cookies, 3, 0, 1, 2)

        self.api_cb = QCheckBox("Dùng YouTube Data API (nhanh & đầy đủ)")
        accel.addWidget(self.api_cb, 4, 0)
        accel.addWidget(QLabel("API key:"), 5, 0)
        self.api_key_edit = QLineEdit(); self.api_key_edit.setPlaceholderText("AIza…")
        self.api_key_edit.setStyleSheet("border: 1px solid black; border-radius: 4px; padding: 2px; color: black;")
        accel.addWidget(self.api_key_edit, 5, 1)

        main_layout.addWidget(accel_group)

        # Xuất file
        export_group = QGroupBox("Xuất file")
        export_layout = QVBoxLayout(export_group)
        export_group.setStyleSheet("""
            QGroupBox {
                background-color: rgba(255, 255, 255, 210);
                border: 1px solid rgba(0, 0, 0, 25);
                border-radius: 12px;
                margin-top: 15px;
                color: #111;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
            }
        """)

        self.split_files_check = QCheckBox("Tự động chia nhỏ file URL")
        export_layout.addWidget(self.split_files_check)

        split_layout = QHBoxLayout()
        split_layout.addWidget(QLabel("Số URL mỗi file:"))
        self.split_count = QSpinBox()
        self.split_count.setRange(1, 100000)
        self.split_count.setValue(100)
        self.split_count.setStyleSheet("border: 1px solid black; border-radius: 4px; padding: 2px; color: black;")
        split_layout.addWidget(self.split_count)
        split_layout.addStretch()
        export_layout.addLayout(split_layout)

        main_layout.addWidget(export_group)

        # Progress + buttons + status
        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.extract_button = QPushButton("Lấy URL Video")
        self.extract_button.setStyleSheet("background-color: #5A3C25; color: white; border-radius: 6px; padding: 6px 12px;")


        self.extract_button.setMinimumHeight(40)
        self.extract_button.clicked.connect(self.start_extraction)
        btn_row.addWidget(self.extract_button)
        main_layout.addLayout(btn_row)

        self.status_label = QLabel("Sẵn sàng")
        main_layout.addWidget(self.status_label)

    # ---- UI actions ----
    def pick_cookies_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn cookies.txt", "", "Text files (*.txt);;All files (*.*)")
        if path:
            self.cookies_path = path
            self.cookies_path_edit.setText(path)
            self.cookies_cb.setChecked(True)

    def start_extraction(self):
        channel = self.channel_id_input.text().strip()
        if not channel:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập ID/handle/URL kênh YouTube!")
            return

        extract_type = ""
        video_count = None
        if self.all_videos_radio.isChecked():
            extract_type = "all"
        elif self.popular_videos_radio.isChecked():
            extract_type = "popular"; video_count = self.popular_count.value()
        elif self.recent_videos_radio.isChecked():
            extract_type = "recent"; video_count = self.recent_count.value()

        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.extract_button.setEnabled(False)
        self.status_label.setText("Đang lấy dữ liệu...")

        use_api = self.api_cb.isChecked()
        api_key = self.api_key_edit.text().strip()
        quick_pop = self.quick_popular_cb.isChecked()
        cookies_path = self.cookies_path if self.cookies_cb.isChecked() else None
        workers = self.workers_spin.value()

        self.worker = YoutubeExtractorThread(
            channel_input=channel,
            extract_type=extract_type,
            video_count=video_count,
            use_api=use_api,
            api_key=api_key,
            quick_popular=quick_pop,
            cookies_path=cookies_path,
            workers=workers
        )
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.extraction_finished)
        self.worker.error_signal.connect(self.extraction_error)
        self.worker.start()

    def update_progress(self, current, total):
        percentage = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(percentage)
        self.status_label.setText(f"Đang xử lý: {current}/{total}" if total else "Đang xử lý...")

    def extraction_finished(self, urls):
        self.video_urls = urls
        self.status_label.setText(f"Hoàn thành! Đã lấy được {len(urls)} URLs.")
        if urls:
            self.save_urls_to_file()
        else:
            QMessageBox.information(self, "Thông báo", "Không tìm thấy URL video nào từ kênh này.")
        self.progress_bar.setVisible(False)
        self.extract_button.setEnabled(True)

    def extraction_error(self, error_message):
        QMessageBox.critical(self, "Lỗi", f"Đã xảy ra lỗi khi lấy dữ liệu: {error_message}")
        self.status_label.setText("Đã xảy ra lỗi!")
        self.progress_bar.setVisible(False)
        self.extract_button.setEnabled(True)

    def save_urls_to_file(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu file")
        if not folder_path:
            return
        try:
            df = pd.DataFrame({"url": self.video_urls})

            if self.split_files_check.isChecked() and len(self.video_urls) > self.split_count.value():
                urls_per_file = self.split_count.value()
                total_files = math.ceil(len(self.video_urls) / urls_per_file)
                for i in range(total_files):
                    start_idx = i * urls_per_file
                    end_idx = min((i + 1) * urls_per_file, len(self.video_urls))
                    file_df = df.iloc[start_idx:end_idx]
                    file_df.to_excel(os.path.join(folder_path, f"youtube_urls_part{i+1}.xlsx"), index=False)
                QMessageBox.information(self, "Thành công", f"Đã lưu {total_files} files tại:\n{folder_path}")
            else:
                file_path = os.path.join(folder_path, "youtube_urls.xlsx")
                df.to_excel(file_path, index=False)
                QMessageBox.information(self, "Thành công", f"Đã lưu file tại:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Lỗi khi lưu file: {str(e)}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = YoutubeUrlExtractor()
    window.show()
    sys.exit(app.exec())
