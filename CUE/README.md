# Công Cụ Lấy URL Kênh YouTube (YouTube URL Extractor)

Ứng dụng giao diện đồ họa (GUI) mạnh mẽ giúp trích xuất danh sách liên kết (URL) video từ bất kỳ kênh YouTube nào. Hỗ trợ nhiều chế độ lọc và tăng tốc độ xử lý.

## ✨ Tính năng chính
- **Trích xuất đa dạng:** Lấy toàn bộ video, video phổ biến nhất (nhiều view nhất) hoặc video gần đây nhất.
- **Hỗ trợ định danh linh hoạt:** Chấp nhận ID kênh (`UC...`), Handle (`@name`) hoặc URL đầy đủ của kênh.
- **Tốc độ cực nhanh:** - Hỗ trợ đa luồng (Multi-threading) khi quét view.
  - Tích hợp **YouTube Data API v3** để lấy dữ liệu hàng nghìn video trong vài giây.
- **Vượt rào cản:** Hỗ trợ nạp file `cookies.txt` để lấy video bị giới hạn độ tuổi hoặc khu vực.
- **Xuất dữ liệu chuyên nghiệp:** - Lưu file dưới định dạng Excel (`.xlsx`).
  - Tính năng tự động chia nhỏ file (ví dụ: mỗi file 100 URL) để tiện quản lý.

## 🚀 Cài đặt

1. **Yêu cầu hệ thống:** Máy tính đã cài đặt [Python 3.10+](https://www.python.org/downloads/).

2. **Cài đặt thư viện:** Mở Terminal/Command Prompt và chạy lệnh:
   ```bash
   pip install -r requirements.txt