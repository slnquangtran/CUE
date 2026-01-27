# CUE
A Python GUI application for bulk extraction of video URLs from YouTube channels. Built with PyQt6, this tool supports multiple input formats, extraction modes, and advanced features like YouTube Data API integration and multi-threaded processing.
### **Core Functionality**
- Extract URLs from YouTube channels using:
  - Channel ID (UC...)
  - Handle (@username)
  - Channel URL
- Multiple extraction modes:
  - **All Videos**: Complete uploads playlist
  - **Popular Videos**: Sorted by view count
  - **Recent Videos**: Latest uploads

### **Advanced Options**
- **YouTube Data API integration**: Fast and complete data retrieval
- **Multi-threading**: Parallel processing for faster extraction
- **Cookies support**: Handle age/region restricted content
- **Quick Popular mode**: Extract from Popular tab (30-60 videos)
- **Deep Popular mode**: Scan entire uploads and sort by views

### **Export Options**
- Save URLs to Excel (.xlsx) format
- Automatic file splitting (configurable batch size)
- Organized file naming

### **Installation**
```bash
pip install -r requirements.txt

### **Prerequisites**
- Python 3.7 or higher
- pip package manager

### **Clone or Download**
```bash
git clone [(https://github.com/slnquangtran/CUE.git)](https://github.com/slnquangtran/CUE.git)





