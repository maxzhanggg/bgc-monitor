"""
访问控制系统 - IP白名单 + 申请审批机制

功能:
1. 白名单IP可直接访问
2. 未授权IP显示申请页面
3. 管理员在dashboard右上角看到待审批通知
4. 一键批准/拒绝访问请求
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent / "data"
ACCESS_FILE = DATA_DIR / "access_control.json"

# 默认管理员IP（你的IP，首次运行时设置）
DEFAULT_ADMIN_IP = None  # 首次访问会自动设置

# ══════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════

def load_access_data():
    """
    加载访问控制数据

    结构:
    {
        "whitelist": {
            "IP地址": {
                "approved_at": "2026-09-15T10:30:00",
                "approved_by": "admin_ip",
                "name": "用户备注名",
                "role": "admin/viewer"
            }
        },
        "pending_requests": {
            "IP地址": {
                "requested_at": "2026-09-15T10:25:00",
                "name": "申请人姓名",
                "reason": "申请理由",
                "device": "user_agent信息"
            }
        },
        "rejected": {
            "IP地址": {
                "rejected_at": "2026-09-15T10:28:00",
                "rejected_by": "admin_ip",
                "reason": "拒绝理由"
            }
        }
    }
    """
    if not ACCESS_FILE.exists():
        return {
            "whitelist": {},
            "pending_requests": {},
            "rejected": {}
        }

    with open(ACCESS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_access_data(data):
    """保存访问控制数据（原子写入）"""
    tmp_file = ACCESS_FILE.with_suffix('.json.tmp')

    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    tmp_file.replace(ACCESS_FILE)

# ══════════════════════════════════════════════════════════════════════
# 权限检查
# ══════════════════════════════════════════════════════════════════════

def check_access(ip_address):
    """
    检查IP是否有访问权限

    返回:
        ("granted", role) - 有权限，返回角色
        ("pending", None) - 已申请但未批准
        ("rejected", None) - 已被拒绝
        ("new", None) - 新IP，需要申请
    """
    # 本地IP（127.0.0.1）直接授权为管理员
    if ip_address in ['127.0.0.1', 'localhost', '::1']:
        data = load_access_data()
        if ip_address not in data["whitelist"]:
            data["whitelist"][ip_address] = {
                "approved_at": datetime.now().isoformat(),
                "approved_by": "auto",
                "name": "本机管理员",
                "role": "admin"
            }
            save_access_data(data)
        return ("granted", "admin")

    data = load_access_data()

    # 检查是否是第一个访问者（Railway部署场景）
    # 如果白名单为空或只有127.0.0.1，则第一个外网访问者自动成为管理员
    has_real_admin = False
    for wl_ip, wl_data in data["whitelist"].items():
        if wl_ip not in ['127.0.0.1', 'localhost', '::1'] and wl_data.get("role") == "admin":
            has_real_admin = True
            break

    if not has_real_admin:
        # 第一个访问者自动成为管理员
        data["whitelist"][ip_address] = {
            "approved_at": datetime.now().isoformat(),
            "approved_by": "first_visitor",
            "name": "首位访问者（管理员）",
            "role": "admin"
        }
        save_access_data(data)
        return ("granted", "admin")

    # 检查白名单
    if ip_address in data["whitelist"]:
        role = data["whitelist"][ip_address].get("role", "viewer")
        return ("granted", role)

    # 检查待审批
    if ip_address in data["pending_requests"]:
        return ("pending", None)

    # 检查已拒绝
    if ip_address in data["rejected"]:
        return ("rejected", None)

    # 新IP - 所有非本机IP都需要申请
    return ("new", None)

def is_admin(ip_address):
    """检查IP是否为管理员"""
    data = load_access_data()
    if ip_address in data["whitelist"]:
        return data["whitelist"][ip_address].get("role") == "admin"
    return False

# ══════════════════════════════════════════════════════════════════════
# 申请管理
# ══════════════════════════════════════════════════════════════════════

def submit_request(ip_address, name, reason="", device_info=""):
    """提交访问申请"""
    data = load_access_data()

    # 防止重复申请
    if ip_address in data["whitelist"]:
        return {"success": False, "message": "已有访问权限"}

    if ip_address in data["pending_requests"]:
        return {"success": False, "message": "申请已提交，等待审批"}

    # 添加申请
    data["pending_requests"][ip_address] = {
        "requested_at": datetime.now().isoformat(),
        "name": name,
        "reason": reason,
        "device": device_info
    }

    save_access_data(data)
    return {"success": True, "message": "申请已提交"}

def get_pending_count():
    """获取待审批数量"""
    data = load_access_data()
    return len(data["pending_requests"])

def get_pending_requests():
    """获取所有待审批申请"""
    data = load_access_data()
    return data["pending_requests"]

def approve_request(ip_address, admin_ip, role="viewer", name_override=None):
    """批准访问申请"""
    data = load_access_data()

    if ip_address not in data["pending_requests"]:
        return {"success": False, "message": "申请不存在"}

    # 获取申请信息
    request = data["pending_requests"].pop(ip_address)

    # 添加到白名单
    data["whitelist"][ip_address] = {
        "approved_at": datetime.now().isoformat(),
        "approved_by": admin_ip,
        "name": name_override or request["name"],
        "role": role,
        "original_request": request
    }

    save_access_data(data)
    return {"success": True, "message": f"已批准 {request['name']} 的访问"}

def reject_request(ip_address, admin_ip, reason=""):
    """拒绝访问申请"""
    data = load_access_data()

    if ip_address not in data["pending_requests"]:
        return {"success": False, "message": "申请不存在"}

    # 移动到已拒绝列表
    request = data["pending_requests"].pop(ip_address)
    data["rejected"][ip_address] = {
        "rejected_at": datetime.now().isoformat(),
        "rejected_by": admin_ip,
        "reason": reason,
        "original_request": request
    }

    save_access_data(data)
    return {"success": True, "message": f"已拒绝 {request['name']} 的访问"}

def revoke_access(ip_address, admin_ip, reason=""):
    """撤销已授权的访问"""
    data = load_access_data()

    if ip_address not in data["whitelist"]:
        return {"success": False, "message": "该IP未在白名单中"}

    # 不能撤销管理员自己
    if ip_address == admin_ip:
        return {"success": False, "message": "不能撤销自己的权限"}

    # 移动到已拒绝列表
    user = data["whitelist"].pop(ip_address)
    data["rejected"][ip_address] = {
        "rejected_at": datetime.now().isoformat(),
        "rejected_by": admin_ip,
        "reason": reason,
        "revoked_user": user
    }

    save_access_data(data)
    return {"success": True, "message": f"已撤销 {user['name']} 的访问权限"}

def get_whitelist():
    """获取白名单列表"""
    data = load_access_data()
    return data["whitelist"]
