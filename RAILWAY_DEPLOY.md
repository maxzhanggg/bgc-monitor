# Railway 部署指南

## 一、准备工作

这个仓库已经包含了Railway部署所需的所有文件：
- ✅ `requirements.txt` - Python依赖
- ✅ `Procfile` - 启动命令
- ✅ `railway.json` - Railway配置
- ✅ `app.py` - 主应用
- ✅ `access_control.py` - 访问控制模块

## 二、推送到GitHub

1. 在GitHub上创建新仓库（例如：`bgc-2026-monitor`）

2. 推送代码：
```bash
cd C:/Users/zhang/Desktop/BGC_2026_Production
git remote add origin https://github.com/你的用户名/bgc-2026-monitor.git
git branch -M main
git push -u origin main
```

## 三、Railway部署步骤

### 1. 登录Railway
访问 https://railway.app/ 并登录

### 2. 创建新项目
- 点击 "New Project"
- 选择 "Deploy from GitHub repo"
- 选择你刚推送的仓库 `bgc-2026-monitor`

### 3. Railway会自动：
- ✅ 检测到Python项目
- ✅ 安装 `requirements.txt` 中的依赖
- ✅ 使用 `Procfile` 启动Streamlit
- ✅ 分配公网URL

### 4. 等待部署完成
- 构建时间约2-3分钟
- 部署成功后会显示绿色状态

### 5. 获取访问地址
- 点击项目卡片
- 在 "Deployments" 标签页找到部署的URL
- 类似：`https://你的项目名.up.railway.app`

## 四、访问控制说明

部署后的访问规则：

1. **本地测试（127.0.0.1）** → 仅在你本机有效
2. **办公室WiFi（192.168.x.x）** → 在Railway上不适用
3. **所有外网访问** → 需要申请审批

⚠️ **重要**：Railway部署后，你从任何地方访问都是外网IP，需要：
- 首次访问时提交申请
- 使用另一个设备/浏览器登录并审批自己
- 或者修改代码添加临时管理员IP

## 五、Railway Free Tier限制

✅ **无自动休眠** - 满足你的要求
- 每月 $5 免费额度
- 约 500小时运行时间
- 适合低流量监控应用

## 六、故障排查

### 部署失败
检查Railway日志：Settings → Logs

### 无法访问
1. 确认部署状态是"Active"
2. 检查Railway生成的URL
3. 查看应用日志

### 访问控制问题
- Railway上所有IP都是外网IP
- 首次访问需要走申请流程
- 可以在代码中硬编码Railway IP为管理员

## 七、下一步

代码已提交到本地Git仓库，现在需要你：
1. 在GitHub创建仓库
2. 推送代码
3. 在Railway连接仓库部署

需要我继续帮你推送到GitHub吗？（需要你的GitHub仓库地址）
