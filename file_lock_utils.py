"""
文件锁工具模块 - 防止并发写入JSON文件时的竞态条件

使用方法:
    with FileLock("data/positions.json"):
        data = json.load(...)
        # 修改数据
        json.dump(data, ...)

跨平台兼容:
- Windows: msvcrt.locking
- Unix/Linux: fcntl.flock
"""

import os
import time
import json
from pathlib import Path
from contextlib import contextmanager

# 检测操作系统
if os.name == 'nt':  # Windows
    import msvcrt
    USE_FCNTL = False
else:  # Unix/Linux/Mac
    import fcntl
    USE_FCNTL = True


class FileLock:
    """
    跨平台文件锁

    防止多个进程/线程同时写入同一个文件
    """

    def __init__(self, file_path, timeout=10):
        """
        Args:
            file_path: 要锁定的文件路径
            timeout: 获取锁的超时时间（秒）
        """
        self.file_path = Path(file_path)
        self.lock_file = self.file_path.with_suffix('.lock')
        self.timeout = timeout
        self.fd = None

    def acquire(self):
        """获取锁"""
        start_time = time.time()

        while True:
            try:
                # 创建锁文件
                self.fd = open(self.lock_file, 'w')

                if USE_FCNTL:
                    # Unix: 使用fcntl
                    fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    # Windows: 使用msvcrt
                    msvcrt.locking(self.fd.fileno(), msvcrt.LK_NBLCK, 1)

                # 获取锁成功
                return True

            except (IOError, OSError):
                # 锁被占用
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(f"无法获取文件锁: {self.file_path} (超时 {self.timeout}s)")

                # 关闭文件句柄，等待后重试
                if self.fd:
                    self.fd.close()
                    self.fd = None

                time.sleep(0.1)  # 等待100ms后重试

    def release(self):
        """释放锁"""
        if self.fd:
            try:
                if USE_FCNTL:
                    fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
                else:
                    msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)
            except:
                pass  # 释放锁失败不影响程序继续

            self.fd.close()
            self.fd = None

        # 删除锁文件
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
        except:
            pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


def atomic_json_write(file_path, data, indent=2):
    """
    原子性写入JSON文件（带文件锁）

    Args:
        file_path: 目标文件路径
        data: 要写入的Python对象
        indent: JSON缩进（默认2）
    """
    file_path = Path(file_path)
    tmp_file = file_path.with_suffix('.tmp')

    # 获取文件锁
    with FileLock(file_path):
        # 写入临时文件
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())  # 强制写入磁盘

        # 原子替换
        tmp_file.replace(file_path)


def atomic_json_read(file_path, default=None):
    """
    安全读取JSON文件（带文件锁）

    Args:
        file_path: 目标文件路径
        default: 文件不存在时的默认返回值

    Returns:
        解析后的Python对象
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return default

    # 获取文件锁（读锁）
    with FileLock(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)


@contextmanager
def safe_json_update(file_path, default=None):
    """
    安全的JSON文件更新上下文管理器

    用法:
        with safe_json_update("data.json", default={}) as data:
            data['key'] = 'value'  # 修改会自动保存

    Args:
        file_path: JSON文件路径
        default: 文件不存在时的默认值
    """
    file_path = Path(file_path)

    # 读取现有数据
    data = atomic_json_read(file_path, default=default)

    # 返回数据供修改
    yield data

    # 自动保存
    atomic_json_write(file_path, data)


# 测试代码
if __name__ == "__main__":
    test_file = Path("test_lock.json")

    print("测试文件锁...")

    # 测试1: 基本写入
    with safe_json_update(test_file, default={}) as data:
        data['test'] = 'success'
        data['timestamp'] = time.time()

    # 测试2: 读取
    result = atomic_json_read(test_file)
    print(f"读取结果: {result}")

    # 测试3: 并发写入（应该安全）
    def concurrent_write(worker_id):
        for i in range(5):
            with safe_json_update(test_file, default={}) as data:
                data[f'worker_{worker_id}'] = i
                time.sleep(0.01)

    import threading
    threads = [threading.Thread(target=concurrent_write, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = atomic_json_read(test_file)
    print(f"并发写入后: {final}")

    # 清理
    test_file.unlink()
    print("✅ 测试完成")
