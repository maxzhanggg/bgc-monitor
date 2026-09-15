"""
BGC 2026 Web Dashboard - 双模式版本 + IP访问控制
比赛前: 测试模式（实时检测信号，不下单）
比赛中: 实战模式（显示真实持仓）

核心功能:
- 测试模式: 每30秒扫描，实时显示信号和虚拟持仓
- 10月11日清空按钮（不清空baseline）
- 10月13日自动切换到实战模式
- IP白名单访问控制 + 申请审批机制

运行: streamlit run app.py --server.address 0.0.0.0
访问: http://localhost:8501

作者: 五专家共识 + ME
更新时间: 2026-09-15
"""

import streamlit as st
import pandas as pd
import json
import time
from datetime import datetime, date, timedelta
from pathlib import Path

# 访问控制 - 保护监控系统
ACCESS_CONTROL_AVAILABLE = True

# 导入访问控制模块
try:
    from access_control import (
        check_access,
        submit_request,
        approve_request,
        reject_request,
        revoke_access,
        get_pending_count,
        get_pending_requests,
        get_whitelist
    )
except ImportError as e:
    ACCESS_CONTROL_AVAILABLE = False
    print(f"⚠️ 访问控制模块不可用: {e}")

# 导入测试模式监控器
try:
    from test_mode_monitor import TestModeMonitor
    TEST_MODE_AVAILABLE = True
except ImportError as e:
    TEST_MODE_AVAILABLE = False
    st.error(f"⚠️ 无法导入test_mode_monitor: {e}")

# 页面配置
st.set_page_config(
    page_title="BGC 2026 Monitor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 全局配置
COMPETITION_START = date(2026, 10, 13)
COMPETITION_END = date(2026, 11, 13)
CLEAN_SLATE_DATE = date(2026, 10, 11)
CAPITAL = 100_000  # $100k USD paper trading capital

# 共享监控状态文件 — 所有 session 从同一个文件读写，保持同步
_MONITOR_STATE_FILE = Path("data/monitor_state.json")

# ══════════════════════════════════════════════════════════════════════
# 访问控制检查
# ══════════════════════════════════════════════════════════════════════

def get_client_ip():
    """获取客户端真实IP（支持代理）"""
    try:
        # Streamlit Cloud / 反向代理环境
        import streamlit.web.server.server as server
        session = server.Server.get_current()._session_mgr.list_active_sessions()[0]

        # 尝试从headers获取真实IP
        headers = session.ws.request.headers if hasattr(session, 'ws') else {}

        # 常见代理header
        for header in ['X-Forwarded-For', 'X-Real-IP', 'CF-Connecting-IP']:
            if header in headers:
                ip = headers[header].split(',')[0].strip()
                return ip

        # 直连IP
        if hasattr(session, 'ws') and hasattr(session.ws, 'request'):
            return session.ws.request.remote_ip
    except:
        pass

    # 本地开发fallback
    return "127.0.0.1"

def show_access_request_page(status, client_ip):
    """显示访问申请页面"""
    st.markdown("### 🔒 BGC 2026 监控系统")
    st.markdown("---")

    if status == "pending":
        st.info("⏳ 您的访问申请正在审批中，请等待管理员批准")
        st.markdown(f"**您的IP:** `{client_ip}`")
        st.markdown("请联系管理员加快审批进度")

    elif status == "rejected":
        st.error("❌ 您的访问申请已被拒绝")
        st.markdown(f"**您的IP:** `{client_ip}`")
        st.markdown("如有疑问请联系管理员")

    elif status == "new":
        st.warning("🔐 此系统需要访问权限")
        st.markdown(f"**您的IP:** `{client_ip}`")

        with st.form("access_request_form"):
            st.markdown("#### 申请访问")
            name = st.text_input("姓名", placeholder="请输入您的姓名")
            reason = st.text_area("申请理由", placeholder="（可选）简要说明访问原因")

            submitted = st.form_submit_button("提交申请")

            if submitted:
                if not name or len(name.strip()) < 2:
                    st.error("请输入有效的姓名")
                else:
                    result = submit_request(
                        ip_address=client_ip,
                        name=name.strip(),
                        reason=reason.strip(),
                        device_info=st.session_state.get('user_agent', 'Unknown')
                    )

                    if result["success"]:
                        st.success(result["message"])
                        st.info("请等待管理员审批，刷新页面查看状态")
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(result["message"])

    st.stop()

def show_admin_panel(client_ip):
    """显示管理员审批面板"""
    pending_count = get_pending_count()

    if pending_count > 0:
        # 显示待审批徽章
        with st.expander(f"🔔 待审批访问申请 ({pending_count})", expanded=False):
            pending_requests = get_pending_requests()

            for req_ip, req_data in pending_requests.items():
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])

                with col1:
                    st.markdown(f"**{req_data['name']}**")
                    st.caption(f"IP: `{req_ip}`")
                    if req_data.get('reason'):
                        st.caption(f"理由: {req_data['reason']}")

                with col2:
                    st.caption(f"申请时间: {req_data['requested_at'][:16]}")

                with col3:
                    if st.button("✅ 批准", key=f"approve_{req_ip}"):
                        result = approve_request(req_ip, client_ip, role="viewer")
                        st.success(result["message"])
                        time.sleep(1)
                        st.rerun()

                with col4:
                    if st.button("❌ 拒绝", key=f"reject_{req_ip}"):
                        result = reject_request(req_ip, client_ip, reason="管理员拒绝")
                        st.warning(result["message"])
                        time.sleep(1)
                        st.rerun()

                st.markdown("---")

            # 显示已授权用户列表
            with st.expander("👥 已授权用户", expanded=False):
                whitelist = get_whitelist()
                for wl_ip, wl_data in whitelist.items():
                    col1, col2, col3 = st.columns([3, 2, 1])

                    with col1:
                        role_badge = "🔑 管理员" if wl_data['role'] == 'admin' else "👁️ 查看者"
                        st.markdown(f"{role_badge} **{wl_data['name']}**")
                        st.caption(f"IP: `{wl_ip}`")

                    with col2:
                        st.caption(f"批准时间: {wl_data['approved_at'][:16]}")

                    with col3:
                        if wl_data['role'] != 'admin' and wl_ip != client_ip:
                            if st.button("🚫 撤销", key=f"revoke_{wl_ip}"):
                                result = revoke_access(wl_ip, client_ip, reason="管理员撤销")
                                st.warning(result["message"])
                                time.sleep(1)
                                st.rerun()

def check_and_enforce_access():
    """检查访问权限并执行访问控制"""
    if not ACCESS_CONTROL_AVAILABLE:
        return True  # 如果访问控制模块不可用，允许访问

    client_ip = get_client_ip()
    status, role = check_access(client_ip)

    if status == "granted":
        # 存储角色到session_state
        st.session_state['user_role'] = role
        st.session_state['user_ip'] = client_ip
        return True
    else:
        # 显示访问申请页面
        show_access_request_page(status, client_ip)
        return False

# ══════════════════════════════════════════════════════════════════════
# 主应用逻辑开始前先检查访问权限
# ══════════════════════════════════════════════════════════════════════

if not check_and_enforce_access():
    st.stop()  # 停止执行，只显示访问申请页面

# ══════════════════════════════════════════════════════════════════════
# 原有功能继续
# ══════════════════════════════════════════════════════════════════════

def _get_monitoring() -> bool:
    try:
        return json.loads(_MONITOR_STATE_FILE.read_text(encoding="utf-8")).get("monitoring", False)
    except Exception:
        return False

def _set_monitoring(value: bool):
    _MONITOR_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MONITOR_STATE_FILE.write_text(
        json.dumps({"monitoring": value, "updated": datetime.now().isoformat()}),
        encoding="utf-8"
    )

def _render_market_status():
    """印尼 IDX / 泰国 SET 开盘状态及倒计时（UTC+7 雅加达/曼谷时间）"""
    now     = datetime.utcnow() + timedelta(hours=7)
    today   = now.date()
    wday    = now.weekday()          # 0=周一 … 6=周日
    now_min = now.hour * 60 + now.minute

    IDX_HOLIDAYS = {date(2026, 10, 28), date(2026, 11, 10)}
    SET_HOLIDAYS = {date(2026, 10, 23)}

    def _mstatus(open_h, open_m, close_h, close_m, lunch=None, holidays=None):
        holidays = holidays or set()
        if wday >= 5:
            return '⚫', '休市', '周末休市', ''
        if today in holidays:
            return '⚫', '节假日', '法定假日休市', ''

        o = open_h * 60 + open_m
        c = close_h * 60 + close_m

        if lunch:
            ls = lunch[0][0] * 60 + lunch[0][1]
            le = lunch[1][0] * 60 + lunch[1][1]
            if ls <= now_min < le:
                rem = le - now_min
                return ('🟡', '午休中',
                        f'午休 {lunch[0][0]:02d}:{lunch[0][1]:02d}–{lunch[1][0]:02d}:{lunch[1][1]:02d}',
                        f'距开盘 {rem // 60}h {rem % 60:02d}m')

        if o <= now_min < c:
            if lunch and now_min < lunch[0][0] * 60 + lunch[0][1]:
                rem = lunch[0][0] * 60 + lunch[0][1] - now_min
                nxt = f'距午休 {rem // 60}h {rem % 60:02d}m'
            else:
                rem = c - now_min
                nxt = f'距收盘 {rem // 60}h {rem % 60:02d}m'
            return ('🟢', '开盘中', f'{open_h:02d}:{open_m:02d}–{close_h:02d}:{close_m:02d}', nxt)

        if now_min < o:
            rem = o - now_min
            return ('🔴', '待开盘', f'开盘 {open_h:02d}:{open_m:02d}',
                    f'距开盘 {rem // 60}h {rem % 60:02d}m')

        return ('🔴', '已收盘', f'收盘 {close_h:02d}:{close_m:02d}', '明日开市')

    idx_s = _mstatus(9,  0, 16,  0, holidays=IDX_HOLIDAYS)
    set_s = _mstatus(10, 0, 17, 30, lunch=((12, 30), (14, 30)), holidays=SET_HOLIDAYS)

    _ALERT = {'🟢': 'success', '🟡': 'warning', '🔴': 'error', '⚫': 'info'}

    st.markdown(f"**🕐 {now.strftime('%H:%M')}** — 市场时间 (UTC+7) · {now.strftime('%m月%d日')}")
    col_idx, col_set = st.columns(2)

    with col_idx:
        e, lbl, detail, nxt = idx_s
        getattr(st, _ALERT[e])(f"{e} **印尼 IDX** — {lbl}")
        st.caption(f"{detail}　　{nxt}" if nxt else detail)

    with col_set:
        e, lbl, detail, nxt = set_s
        getattr(st, _ALERT[e])(f"{e} **泰国 SET** — {lbl}")
        st.caption(f"{detail}　　{nxt}" if nxt else detail)

# ══════════════════════════════════════════════════════════════
# 模式判断
# ══════════════════════════════════════════════════════════════

today = date.today()

if today < COMPETITION_START:
    MODE = "TEST"
else:
    MODE = "LIVE"

# ══════════════════════════════════════════════════════════════
# 侧边栏 - 系统信息
# ══════════════════════════════════════════════════════════════

with st.sidebar:
    st.header("📊 系统状态")

    if MODE == "TEST":
        st.success("🟢 监控运行中")
        days_to_comp = (COMPETITION_START - today).days
        st.metric("距离比赛", f"{days_to_comp} 天")

        if today == CLEAN_SLATE_DATE:
            st.warning("⚠️ 清空日（比赛前2天）")

    else:
        st.success("🚀 比赛进行中")
        days_elapsed = (today - COMPETITION_START).days
        days_remaining = (COMPETITION_END - today).days
        st.metric("比赛进行", f"D{days_elapsed}")
        st.metric("剩余天数", f"{days_remaining} 天")

    st.divider()

    # ─── Baseline数据采集状态 ───
    st.subheader("📂 Baseline数据状态")
    st.caption("每日09:00 auto_collector.py 采集")

    collection_status_file = Path("data/daily_snapshots/collection_status.json")
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    if collection_status_file.exists():
        with open(collection_status_file, 'r') as f:
            cst = json.load(f)

        last_target = cst.get('target_date', '未知')
        last_run = cst.get('last_run', '')
        success = cst.get('success', 0)
        fail = cst.get('fail', 0)
        total = cst.get('total', 0)

        # 判断昨日数据是否已采集
        if last_target == yesterday:
            if fail == 0:
                st.success(f"✅ 昨日数据已获取")
            else:
                st.warning(f"⚠️ 昨日数据部分缺失")
        else:
            st.error(f"❌ 昨日数据未采集")
            st.caption(f"最近采集日期: {last_target}")

        # 详细信息
        st.caption(f"目标日期: {last_target}")
        st.caption(f"成功: {success} / {total} 只")
        if fail > 0:
            st.caption(f"失败: {fail} 只")
        if last_run:
            run_time = last_run[:16].replace('T', ' ')
            st.caption(f"采集时间: {run_time}")
    else:
        st.error("❌ 未找到采集记录")
        st.caption("请运行 auto_collector.py")

    st.caption("⚠️ Baseline数据与实时行情无关")

    # 手动采集按钮
    if st.button("🔄 手动采集+计算Baseline", use_container_width=True):
        with st.spinner("正在采集历史数据..."):
            import subprocess

            # 步骤1: 采集历史数据
            try:
                result = subprocess.run(
                    ["python", "auto_collector.py", "--once"],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    encoding='utf-8',
                    errors='ignore'
                )

                if result.returncode == 0:
                    st.success("✅ 历史数据采集完成")
                else:
                    st.error(f"❌ 采集失败: {result.stderr[:200]}")
                    st.stop()

            except subprocess.TimeoutExpired:
                st.error("❌ 采集超时（10分钟）")
                st.stop()
            except Exception as e:
                st.error(f"❌ 采集错误: {e}")
                st.stop()

        with st.spinner("正在计算Baseline指标..."):
            # 步骤2: 计算baseline
            try:
                result = subprocess.run(
                    ["python", "calculate_baselines.py"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    encoding='utf-8',
                    errors='ignore'
                )

                if result.returncode == 0:
                    st.success("✅ Baseline计算完成")
                    st.info("已更新: median_volume_20d/60d, MAD, price_stats")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error(f"❌ 计算失败: {result.stderr[:200]}")

            except subprocess.TimeoutExpired:
                st.error("❌ 计算超时（5分钟）")
            except Exception as e:
                st.error(f"❌ 计算错误: {e}")

    st.divider()

    # ─── 自动化任务调度 ───
    st.subheader("⏰ 自动化调度")
    st.caption("Windows任务计划 (仅本机)")

    import subprocess as _sp
    import socket as _sock

    # 只在本机显示（按主机名判断）
    _ALLOWED_HOST = "ZJHHH"  # 本机主机名
    _on_allowed_host = _sock.gethostname().upper() == _ALLOWED_HOST.upper()

    def _task_exists(name):
        r = _sp.run(["schtasks", "/query", "/tn", name],
                    capture_output=True, text=True)
        return r.returncode == 0

    def _create_task(name, script, time_str):
        script_path = str(Path(__file__).parent / script)
        cmd = ["schtasks", "/create", "/tn", name,
               "/tr", f'python "{script_path}"',
               "/sc", "daily", "/st", time_str, "/f"]
        r = _sp.run(cmd, capture_output=True, text=True)
        return r.returncode == 0

    def _delete_task(name):
        r = _sp.run(["schtasks", "/delete", "/tn", name, "/f"],
                    capture_output=True, text=True)
        return r.returncode == 0

    TASKS = [
        ("BGC_2026_DataCollector",    "auto_collector.py --once", "08:30", "📥 每日数据采集 08:30"),
        ("BGC_2026_ExclusionUpdate",  "update_exclusions_daily.py", "17:30", "🔄 排除列表更新 17:30"),
    ]

    if not _on_allowed_host:
        st.caption(f"⚠️ 仅限本机 ({_ALLOWED_HOST}) 可配置")
    else:
        for task_name, script, time_str, label in TASKS:
            exists = _task_exists(task_name)
            col_label, col_toggle = st.columns([3, 1])
            with col_label:
                if exists:
                    st.markdown(f"🟢 {label}")
                else:
                    st.markdown(f"🔴 {label}")
            with col_toggle:
                if exists:
                    if st.button("关闭", key=f"off_{task_name}", use_container_width=True):
                        if _delete_task(task_name):
                            st.success("已停用")
                            st.rerun()
                        else:
                            st.error("停用失败（需管理员权限）")
                else:
                    if st.button("开启", key=f"on_{task_name}", use_container_width=True):
                        if _create_task(task_name, script, time_str):
                            st.success("已启用")
                            st.rerun()
                        else:
                            st.error("启用失败（需管理员权限）")

        st.caption("⚠️ 开启/关闭需要管理员权限运行 Streamlit")

    st.divider()
    st.caption(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ══════════════════════════════════════════════════════════════
# 测试模式
# ══════════════════════════════════════════════════════════════

if MODE == "TEST":
    # 标题
    st.title("📊 BGC 2026 实时监控")
    st.caption("信号检测与持仓追踪")

    # 管理员面板（右上角）
    if st.session_state.get('user_role') == 'admin':
        show_admin_panel(st.session_state.get('user_ip'))

    # 市场时间状态
    _render_market_status()

    if not TEST_MODE_AVAILABLE:
        st.error("❌ test_mode_monitor.py 未正确加载，无法运行测试模式")
        st.stop()

    # 初始化测试监控器（session state）
    if 'test_monitor' not in st.session_state:
        with st.spinner("🔧 初始化测试监控器..."):
            st.session_state.test_monitor = TestModeMonitor()
        st.success("✅ 监控器初始化完成")

    test_monitor = st.session_state.test_monitor

    # ─── 控制按钮区 ───
    st.divider()
    col_btn1, col_btn2, col_btn3, col_btn4 = st.columns([1, 1, 1, 2])

    with col_btn1:
        if st.button("▶️ 启动监控", use_container_width=True):
            _set_monitoring(True)
            st.rerun()

    with col_btn2:
        if st.button("⏸️ 暂停监控", use_container_width=True):
            _set_monitoring(False)
            st.rerun()

    with col_btn3:
        if st.button("🔄 手动刷新", use_container_width=True):
            st.rerun()

    with col_btn4:
        if today == CLEAN_SLATE_DATE:
            if st.button("🧹 清空测试数据（比赛前2天）", type="primary", use_container_width=True):
                with st.spinner("正在清空..."):
                    test_monitor.clear_test_data()
                st.success("✅ 测试数据已清空！Baseline保持不变")
                time.sleep(2)
                st.rerun()

    st.divider()

    # ─── 实时监控主循环 ───

    if _get_monitoring():
        # 监控状态指示
        status_col1, status_col2 = st.columns([3, 1])
        with status_col1:
            st.success("🟢 实时监控中... (30秒自动刷新)")
        with status_col2:
            scan_count = test_monitor.total_scans
            st.metric("扫描次数", scan_count)

        # 创建占位符
        signal_container = st.container()
        position_container = st.container()
        stats_container = st.container()

        # 运行一次扫描
        with st.spinner("🔍 扫描中..."):
            signals = test_monitor.run_test_scan()

        # ═══ 1. 显示实时信号 ═══
        with signal_container:
            st.header("🔍 实时信号检测")
            st.caption(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            if signals:
                st.info(f"🚨 检测到 {len(signals)} 个信号")

                for sig in signals:
                    # 信号卡片
                    with st.expander(
                        f"{'🔥' if sig['tier'] <= 2 else '📊'} "
                        f"{sig['ticker']} - {sig['signal']} (Tier {sig['tier']})",
                        expanded=(sig['tier'] <= 2)  # Tier 1-2自动展开
                    ):
                        # 指标行
                        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

                        with metric_col1:
                            st.metric("成交量倍数", f"{sig['vol_ratio']:.1f}x")

                        with metric_col2:
                            st.metric("价格涨幅", f"{sig['change_pct']*100:.1f}%")

                        with metric_col3:
                            st.metric("建议仓位", f"${sig['allocation']:,}")

                        with metric_col4:
                            st.metric("信心度", f"{sig.get('confidence', 0)}%")

                        # 详细信息
                        st.info(f"📝 {sig['note']}")
                        st.success(f"💰 {sig['action']}")

                        if 'action_detail' in sig:
                            with st.expander("📋 详细操作"):
                                st.text(sig['action_detail'])

                        # 历史类比
                        if 'analog' in sig and sig['analog']:
                            st.caption(f"📚 历史案例: {sig['analog']}")

                        if 'expected_return' in sig:
                            st.caption(f"🎯 预期收益: {sig['expected_return']}")

            else:
                st.info("✓ 暂无信号")

        st.divider()

        # ═══ 2. 显示虚拟持仓 ═══
        with position_container:
            st.header("📊 虚拟持仓（测试）")

            if test_monitor.test_positions:
                # 更新持仓价格
                current_prices = {sig['ticker']: sig['price'] for sig in signals}
                test_monitor.update_test_positions(current_prices)

                # 筛选OPEN持仓
                open_positions = [p for p in test_monitor.test_positions if p['status'] == 'OPEN']

                if open_positions:
                    # 转换为DataFrame
                    pos_data = []
                    for pos in open_positions:
                        pos_data.append({
                            'Ticker': pos['ticker'],
                            'Market': pos['market'],
                            'Tier': f"S{pos['tier']}",
                            '入场时间': pos['entry_time'].strftime('%m-%d %H:%M'),
                            '入场价': f"${pos['entry_price']:.4f}",
                            '当前价': f"${pos.get('current_price', pos['entry_price']):.4f}",
                            '收益率': pos.get('current_return', 0),
                            '最大收益': pos.get('max_return', 0),
                            '持有时长': f"{pos.get('holding_hours', 0):.1f}h",
                            '仓位': f"${pos['allocation']:,}",
                            '信号类型': pos['signal_type']
                        })

                    df = pd.DataFrame(pos_data)

                    # 格式化收益率列
                    df['收益率'] = df['收益率'].apply(lambda x: f"{x*100:+.1f}%")
                    df['最大收益'] = df['最大收益'].apply(lambda x: f"{x*100:+.1f}%")

                    # 显示表格
                    st.dataframe(
                        df,
                        use_container_width=True,
                        height=min(400, len(df) * 35 + 38)
                    )

                    # 持仓总结
                    summary_col1, summary_col2, summary_col3 = st.columns(3)

                    with summary_col1:
                        total_allocation = sum(p['allocation'] for p in open_positions)
                        st.metric("总仓位", f"${total_allocation:,}")

                    with summary_col2:
                        returns = [p.get('current_return', 0) for p in open_positions]
                        avg_return = sum(returns) / len(returns)
                        st.metric("平均收益", f"{avg_return*100:+.1f}%")

                    with summary_col3:
                        winners = len([r for r in returns if r > 0])
                        st.metric("盈利数/总数", f"{winners}/{len(returns)}")

                else:
                    st.info("✓ 暂无持仓")

            else:
                st.info("✓ 暂无持仓")

        st.divider()

        # ═══ 3. 显示测试统计 ═══
        with stats_container:
            st.header("📈 测试统计")

            stats = test_monitor.get_test_statistics()

            # 第一行指标
            stat_col1, stat_col2, stat_col3, stat_col4, stat_col5 = st.columns(5)

            with stat_col1:
                st.metric("累计信号", stats['total_positions'])

            with stat_col2:
                st.metric("当前持仓", stats['open_positions'])

            with stat_col3:
                st.metric("平均收益", f"{stats['avg_return']*100:+.1f}%")

            with stat_col4:
                st.metric("最大收益", f"{stats['max_return']*100:+.1f}%")

            with stat_col5:
                st.metric("胜率", f"{stats['win_rate']*100:.0f}%")

            # 按Tier统计
            if stats['positions_by_tier']:
                st.caption("按信号层级统计:")
                tier_cols = st.columns(len(stats['positions_by_tier']))
                for idx, (tier, count) in enumerate(sorted(stats['positions_by_tier'].items())):
                    with tier_cols[idx]:
                        st.metric(tier, count)

        # 自动刷新（30秒）
        time.sleep(30)
        st.rerun()

    else:
        # 监控已暂停
        st.warning("⏸️ 监控已暂停")
        st.info("点击'启动监控'开始实时检测信号")

        # 显示静态统计
        if test_monitor.test_positions:
            st.subheader("📊 当前测试数据概览")
            stats = test_monitor.get_test_statistics()

            overview_col1, overview_col2, overview_col3 = st.columns(3)

            with overview_col1:
                st.metric("累计扫描", stats['total_scans'])

            with overview_col2:
                st.metric("累计信号", stats['total_positions'])

            with overview_col3:
                st.metric("当前持仓", stats['open_positions'])

# ══════════════════════════════════════════════════════════════
# 实战模式
# ══════════════════════════════════════════════════════════════

elif MODE == "LIVE":
    st.title("🚀 BGC 2026 实战模式")
    st.caption("比赛进行中 - 真实持仓监控")

    # 管理员面板（右上角）
    if st.session_state.get('user_role') == 'admin':
        show_admin_panel(st.session_state.get('user_ip'))

    _render_market_status()

    st.info("""
    💡 **提示**: 实战模式下，真实交易由 `production_monitor.py` 执行

    此界面用于：
    - 监控真实持仓
    - 查看历史信号
    - 显示收益统计

    要查看完整日志和实时交易，请运行：
    ```
    python production_monitor.py
    ```
    """)

    st.divider()

    # 读取真实持仓（从production_monitor的positions.json）
    positions_file = Path("data/positions.json")

    if positions_file.exists():
        with open(positions_file, 'r', encoding='utf-8') as f:
            portfolio = json.load(f)

        positions = portfolio.get('positions', [])

        if positions:
            st.subheader("💰 当前持仓")

            # 转换为DataFrame
            pos_df = pd.DataFrame(positions)
            st.dataframe(pos_df, use_container_width=True)

            # 统计
            total_value = sum(p.get('current_value', 0) for p in positions)
            total_cost = sum(p.get('cost', 0) for p in positions)
            total_return = (total_value - total_cost) / total_cost if total_cost > 0 else 0

            metric_col1, metric_col2, metric_col3 = st.columns(3)

            with metric_col1:
                st.metric("总持仓成本", f"${total_cost:,.0f}")

            with metric_col2:
                st.metric("当前市值", f"${total_value:,.0f}")

            with metric_col3:
                st.metric("总收益率", f"{total_return*100:+.1f}%")

        else:
            st.info("✓ 当前无持仓")

    else:
        st.warning("⚠️ 未找到持仓文件，请确保 production_monitor.py 正在运行")

# ══════════════════════════════════════════════════════════════
# 页脚
# ══════════════════════════════════════════════════════════════

st.divider()
st.caption("BGC 2026 Trading Competition Monitor")
