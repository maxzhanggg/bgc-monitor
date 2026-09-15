"""
测试访问控制UI - 验证完整工作流
运行: streamlit run test_access_ui.py
"""

import streamlit as st
from access_control import check_access, submit_request, get_pending_count
import socket

st.set_page_config(page_title="访问控制测试", page_icon="🔐", layout="wide")

# 模拟获取IP
def get_client_ip():
    """模拟IP获取"""
    if 'simulated_ip' not in st.session_state:
        st.session_state.simulated_ip = '192.168.1.100'  # 默认第一个访客（管理员）
    return st.session_state.simulated_ip

st.title("🔐 访问控制系统测试")
st.caption("测试多用户访问申请和审批流程")

# IP模拟器
st.sidebar.header("🧪 IP模拟器")
st.sidebar.caption("模拟不同用户访问")

ip_options = {
    "管理员 (192.168.1.100)": "192.168.1.100",
    "台湾访客 (123.45.67.89)": "123.45.67.89",
    "其他访客 (111.222.333.444)": "111.222.333.444",
}

selected_label = st.sidebar.selectbox("选择身份", list(ip_options.keys()))
st.session_state.simulated_ip = ip_options[selected_label]

current_ip = get_client_ip()
st.sidebar.info(f"当前模拟IP:\n`{current_ip}`")

# 检查访问权限
status, role = check_access(current_ip)

st.divider()

# 显示当前状态
col1, col2, col3 = st.columns(3)

with col1:
    status_emoji = {
        'granted': '✅',
        'pending': '⏳',
        'rejected': '❌',
        'new': '🆕'
    }
    st.metric("访问状态", f"{status_emoji.get(status, '❓')} {status.upper()}")

with col2:
    role_emoji = {
        'admin': '👑',
        'viewer': '👁️',
        None: '❌'
    }
    st.metric("用户角色", f"{role_emoji.get(role, '❓')} {role.upper() if role else 'NONE'}")

with col3:
    pending = get_pending_count()
    st.metric("待审批请求", f"🔔 {pending}")

st.divider()

# 根据状态显示不同界面
if status == 'granted':
    if role == 'admin':
        st.success("🎉 你是管理员！")
        st.info("第一个访问系统的用户自动成为管理员")

        # 管理员面板
        st.subheader("👑 管理员面板")

        if pending > 0:
            st.warning(f"⚠️ 有 {pending} 个待审批的访问请求")

            # 这里简化显示，实际app.py会调用show_admin_panel
            st.caption("在实际系统中，右上角会显示红色数字标记")
            st.code("show_admin_panel(current_ip)", language="python")
        else:
            st.info("✓ 当前无待审批请求")

    elif role == 'viewer':
        st.success("✅ 访问已授权（查看者）")
        st.info("你可以查看所有数据，但无法修改配置")

elif status == 'new':
    st.warning("🆕 首次访问 - 需要申请权限")

    with st.form("access_request_form"):
        st.subheader("📝 申请访问权限")

        name = st.text_input("姓名", placeholder="例如: 李华")
        reason = st.text_area("申请理由", placeholder="例如: 我是台湾团队成员，需要查看实时监控数据")

        submitted = st.form_submit_button("提交申请", use_container_width=True)

        if submitted:
            if not name or not reason:
                st.error("请填写完整信息")
            else:
                result = submit_request(
                    ip=current_ip,
                    name=name,
                    reason=reason,
                    user_agent="Test Browser"
                )

                if result['success']:
                    st.success("✅ " + result['message'])
                    st.info("请等待管理员审批，刷新页面查看状态")
                    st.balloons()
                else:
                    st.error("❌ " + result['message'])

elif status == 'pending':
    st.info("⏳ 你的申请正在等待管理员审批...")
    st.caption("请稍后刷新页面查看状态")

    if st.button("🔄 刷新状态", use_container_width=True):
        st.rerun()

elif status == 'rejected':
    st.error("❌ 访问申请已被拒绝")
    st.caption("如有疑问，请联系管理员")

st.divider()

# 测试说明
with st.expander("📖 测试说明"):
    st.markdown("""
### 测试流程

1. **首次访问（管理员）**
   - 左侧选择"管理员 (192.168.1.100)"
   - 第一个访客自动成为管理员
   - 状态显示为 `GRANTED` / `ADMIN`

2. **新用户访问（台湾访客）**
   - 左侧选择"台湾访客 (123.45.67.89)"
   - 状态显示为 `NEW`
   - 填写申请表单并提交
   - 状态变为 `PENDING`

3. **管理员审批**
   - 切换回"管理员 (192.168.1.100)"
   - 看到"待审批请求"数字增加
   - 在实际系统中，右上角会显示🔔1
   - 点击后可以批准/拒绝

4. **查看审批结果**
   - 切换回"台湾访客"
   - 如果被批准，状态变为 `GRANTED` / `VIEWER`
   - 可以正常查看系统数据

### 实际部署后的效果

- **无需端口转发/Ngrok**：只要能访问到你的Streamlit URL即可
- **自动IP识别**：系统自动记录每个访客的IP
- **右上角通知**：管理员看到🔔标记 + 红色数字
- **一键审批**：点击查看详情，批准/拒绝按钮
    """)

st.caption("✅ 访问控制系统测试 v1.0")
