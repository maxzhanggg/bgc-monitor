# 🔄 重启指南

## ✅ 访问控制已完成集成

所有代码已更新完毕，现在需要重启Streamlit让新代码生效。

---

## 📋 重启步骤

### 1. 停止旧进程
按 `Ctrl + C` 在运行Streamlit的命令行窗口中

或者强制关闭：
```bash
taskkill /F /PID 22720
```

### 2. 启动新版本
```bash
cd C:\Users\zhang\Desktop\BGC_2026_Production
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

### 3. 访问网站
打开浏览器访问：http://localhost:8501

---

## ✨ 新功能说明

### 访问规则（已更新）

**本机（127.0.0.1）**
- ✅ 自动识别为管理员
- ✅ 直接进入，无需申请

**同WiFi设备（192.168.x.x）**
- ✅ 自动通过
- ✅ 适合办公室内其他电脑/手机

**外网访问（台湾/香港等）**
- 📝 首次访问显示申请表单
- ⏳ 填写姓名和理由后提交
- 🔔 你的页面右上角显示红色数字徽章
- ✅ 点击批准后对方可立即访问

---

## 🎯 管理员功能

重启后，你访问 http://localhost:8501 会看到：

**右上角管理面板**
- 🔔 待审批申请 (X) - 展开可看到申请列表
- ✅ 批准 / ❌ 拒绝 按钮
- 👥 已授权用户列表
- 🚫 撤销权限（针对非管理员）

---

## 🌐 让台湾朋友访问

重启后，使用以下任一方式：

### 方式A：Ngrok（推荐，最简单）
```bash
# 下载 https://ngrok.com/download
ngrok http 8501
```
把生成的URL（如 `https://xxxx.ngrok.io`）发给台湾朋友

### 方式B：端口转发
1. 路由器管理页面设置：外网8501 → 192.168.x.x:8501（你的内网IP）
2. 查询公网IP：访问 https://ip.cn
3. 把 `http://你的公网IP:8501` 发给台湾朋友

---

## 🔧 验证访问控制是否生效

重启后：

1. **本机测试**：http://localhost:8501 → 应该直接进入
2. **模拟外网**：用手机4G访问 → 应该看到申请表单
3. **管理面板**：右上角应该有 "🔔 待审批申请" 展开器

---

## 📊 已完成的更新

✅ `access_control.py` - WiFi自动通过规则
✅ `app.py` - 导入访问控制模块
✅ `app.py` - 管理员面板显示（TEST和LIVE模式）
✅ `app.py` - 访问权限检查逻辑

---

## ⚠️ 注意事项

- 首次启动可能需要15秒加载依赖
- 确保 `data/` 文件夹有写权限
- 端口8501如果被占用会自动分配8502
- 访问记录保存在 `data/access_requests.json`

---

## 🆘 如果遇到问题

**问题1：端口被占用**
```bash
netstat -ano | findstr :8501
taskkill /F /PID <进程号>
```

**问题2：访问控制不生效**
检查 `data/access_requests.json` 是否存在：
```bash
dir data\access_requests.json
```

**问题3：管理员面板不显示**
检查 `access_control.py` 是否在同目录：
```bash
dir access_control.py
```

---

重启后就能用了！🚀
