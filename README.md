# Telegram 待辦事項協作機器人 🤖

一個安全的協作式待辦事項管理機器人，支持房間系統和實時通知功能。

## ✨ 主要功能

### 🔒 安全房間系統
- **創建房間** - 設置房間名稱和密碼，獲得唯一4位數房間號
- **加入房間** - 通過房間號和密碼加入現有房間
- **數據隔離** - 每個房間的待辦事項完全獨立

### 📝 待辦事項管理
- **添加待辦** - 支持多個分類（遊戲、影視、行動）
- **查詢待辦** - 查看所有或按分類查詢
- **刪除待辦** - 選擇性刪除已完成事項
- **實時通知** - 房間成員操作時自動通知所有人

### 🛡️ 安全特性
- 密碼SHA256哈希存儲
- 房間號唯一性驗證
- 需要密碼驗證才能加入房間

## 🚀 快速開始

### 環境要求
- Python 3.8+
- PostgreSQL 數據庫
- Telegram Bot Token

### 安裝步驟

1. **克隆項目**
```bash
git clone <your-repo-url>
cd telegram-todo-bot
安裝依賴
<BASH>
pip install -r requirements.txt
設置環境變量
<BASH>
export TELEGRAM_BOT_TOKEN="你的機器人token"
export DATABASE_URL="postgresql://username:password@host:port/database"
初始化數據庫
<BASH>
python bot.py
Docker 部署
<BASH>
docker build -t todo-bot .
docker run -d \
  -e TELEGRAM_BOT_TOKEN="你的token" \
  -e DATABASE_URL="你的數據庫連接" \
  --name todo-bot \
  todo-bot
  📖 使用指南
1. 啟動機器人
在Telegram中搜索你的機器人，發送 /start 開始使用

2. 創建或加入房間
創建房間：點擊「🏠 創建房間」，輸入房間名稱和密碼
加入房間：點擊「🔑 加入房間」，輸入房間號和密碼
3. 管理待辦事項
添加待辦：選擇分類 → 輸入事項內容
查看待辦：查看所有或按分類查看
刪除待辦：選擇要刪除的事項
4. 協作功能
房間成員的操作會實時通知所有人
每個房間最多支持10人協作

數據庫結構
users - 用戶信息
rooms - 房間信息
room_members - 房間成員關係
todos - 待辦事項
🤝 貢獻指南
Fork 本項目
創建特性分支 (git checkout -b feature/AmazingFeature)
提交更改 (git commit -m 'Add some AmazingFeature')
推送到分支 (git push origin feature/AmazingFeature)
開啟Pull Request
📄 許可證
本項目採用 MIT 許可證 - 查看 LICENSE 文件了解詳情

🆘 支持
如果遇到問題，請：

查看 故障排除 章節
檢查日誌文件獲取詳細錯誤信息
提交 Issue 並提供相關信息