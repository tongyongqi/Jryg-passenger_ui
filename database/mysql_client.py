# -*- coding: utf-8 -*-
# 这个文件的功能是提供通用的 MySQL 数据库连接、查询及事务操作客户端的代码
"""
==========================================================================
🌐 优惠券与工单自动化调度系统 - MySQL 数据库客户端工具 (mysql_client.py)
==========================================================================
提供统一的、稳健的数据库操作接口：
1. 自动检测并动态安装依赖库 `pymysql`，确保用户能够一键即用。
2. 支持 Context Manager 模式 (`with MySQLClient() as client:`)，自动进行资源的开启和关闭，防止连接泄露。
3. 提供了对 `SELECT` 等查询操作的 `execute_query` (返回 Dict 格式结果) 和针对 `INSERT/UPDATE/DELETE` 等写操作的 `execute_non_query` (事务自动提交与异常回滚)。
"""

import os
import sys
import subprocess

# 确保将项目根目录优先添加到 python path 使得模块 and 配置能被正常载入
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# 自动检测并尝试安装 pymysql 依赖，确保即装即用
try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:
    print("⚠️ 检测到当前环境未安装 `pymysql` 依赖，正在尝试自动安装...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pymysql"])
        import pymysql
        from pymysql.cursors import DictCursor
        print("🎉 `pymysql` 依赖安装成功！")
    except Exception as import_err:
        print(f"❌ 自动安装 `pymysql` 失败，请在终端手动运行 'pip install pymysql'！错误信息: {import_err}")
        raise import_err

import config_business
from logger.database_logger import database_logger as logger


class MySQLClient:
    def __init__(self, db_name=None, custom_config=None):
        """
        初始化数据库客户端。
        
        参数:
          db_name (str, optional): 默认连接的数据库名称。
          custom_config (dict, optional): 自定义连接配置，若不传则默认读取 config_business.DB_CONFIG。
        """
        # 读取配置，并支持自定义参数覆盖
        base_config = getattr(config_business, "DB_CONFIG", {})
        self.config = {
            "host": base_config.get("host", "172.19.0.132"),
            "port": base_config.get("port", 3306),
            "user": base_config.get("user", "jryg_tx_test"),
            "password": base_config.get("password", "3G$opYrLCnqZxa6a"),
            "charset": base_config.get("charset", "utf8mb4"),
        }
        
        # 允许在实例化或调用时注入具体的数据库名称
        if db_name:
            self.config["database"] = db_name
            
        if custom_config:
            self.config.update(custom_config)
            
        self.connection = None

    def connect(self):
        """
        建立数据库连接。
        """
        if self.connection and self.connection.open:
            return self.connection
            
        try:
            logger.info(f"正在尝试连接 MySQL 数据库 ({self.config['host']}:{self.config['port']})...")
            self.connection = pymysql.connect(
                host=self.config["host"],
                port=self.config["port"],
                user=self.config["user"],
                password=self.config["password"],
                database=self.config.get("database"),
                charset=self.config["charset"],
                cursorclass=DictCursor,
                connect_timeout=10  # 10秒连接超时
            )
            logger.info("🎉 MySQL 数据库连接成功！")
            return self.connection
        except Exception as err:
            logger.error(f"❌ 建立数据库连接失败: {err}")
            raise err

    def close(self):
        """
        关闭数据库连接。
        """
        if self.connection and self.connection.open:
            try:
                self.connection.close()
                logger.info("🔌 数据库连接已安全关闭。")
            except Exception as err:
                logger.warn(f"⚠️ 关闭数据库连接时发生异常: {err}")
        self.connection = None

    def execute_query(self, sql, params=None, db_name=None):
        """
        执行查询类 SQL (SELECT)，并以列表字典(List[Dict]) 格式返回。
        
        参数:
          sql (str): SQL 语句
          params (tuple/dict/list, optional): SQL 绑定参数
          db_name (str, optional): 临时切换查询的目标数据库
        """
        self.connect()
        if db_name:
            self.connection.select_db(db_name)
            
        try:
            with self.connection.cursor() as cursor:
                logger.info(f"执行查询 SQL: {sql} | 参数: {params}")
                cursor.execute(sql, params)
                results = cursor.fetchall()
                logger.info(f"🔍 查询成功，共检索到 {len(results)} 行数据。")
                return results
        except Exception as err:
            logger.error(f"❌ 执行查询 SQL 失败: {err} | SQL: {sql}")
            raise err

    def execute_non_query(self, sql, params=None, db_name=None):
        """
        执行非查询类 SQL (INSERT, UPDATE, DELETE)，自动处理事务提交与异常回滚。
        
        参数:
          sql (str): SQL 语句
          params (tuple/dict/list, optional): SQL 绑定参数
          db_name (str, optional): 临时切换的目标数据库
          
        返回:
          dict: 包含 affected_rows (受影响行数) 和 last_row_id (最后插入的主键ID)
        """
        self.connect()
        if db_name:
            self.connection.select_db(db_name)
            
        try:
            with self.connection.cursor() as cursor:
                logger.info(f"执行非查询 SQL: {sql} | 参数: {params}")
                affected_rows = cursor.execute(sql, params)
                self.connection.commit()
                last_row_id = cursor.lastrowid
                logger.info(f"💾 事务提交成功。受影响行数: {affected_rows} | 插入ID: {last_row_id}")
                return {
                    "affected_rows": affected_rows,
                    "last_row_id": last_row_id
                }
        except Exception as err:
            if self.connection:
                self.connection.rollback()
                logger.warn("↩️ 发生异常，数据库事务已回滚！")
            logger.error(f"❌ 执行非查询 SQL 失败: {err} | SQL: {sql}")
            raise err

    # 支持 Python Context Manager 模式
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ==========================================
# 🛠️ 常用高频业务数据库操作助手函数 (DB Helper)
# ==========================================

def get_user_by_mobile(mobile: str):
    """
    根据手机号查询用户信息
    支持普通手机号和 MD5 加密手机号
    """
    import hashlib
    with MySQLClient() as client:
        # 1. 尝试直接查询
        sql_direct = "SELECT * FROM jryg_user.users WHERE Mobile = %s;"
        res = client.execute_query(sql_direct, (mobile,))
        if res:
            return res
        
        # 2. 尝试 MD5 加密字段匹配查询
        md5_val = hashlib.md5(mobile.encode('utf-8')).hexdigest()
        sql_md5 = "SELECT * FROM jryg_user.users WHERE Mobile LIKE CONCAT('%%120', %s);"
        res_md5 = client.execute_query(sql_md5, (md5_val,))
        if res_md5:
            return res_md5
            
        # 3. 模糊匹配查询
        sql_like = "SELECT * FROM jryg_user.users WHERE Mobile LIKE %s;"
        return client.execute_query(sql_like, (f"%{mobile}%",))


def get_user_by_id(user_id: int):
    """
    根据 UserID 获取用户信息
    """
    with MySQLClient() as client:
        sql = "SELECT * FROM jryg_user.users WHERE UserID = %s;"
        return client.execute_query(sql, (user_id,))


def get_user_coupons(user_id: int):
    """
    查看用户的优惠券列表
    """
    with MySQLClient() as client:
        sql = "SELECT * FROM jryg_coupon.coupon_user_new WHERE user_id = %s;"
        return client.execute_query(sql, (user_id,))


def get_user_coupons_by_mobile(mobile: str):
    """
    【高频连表查询】根据手机号（自动支持普通/MD5密文手机号）一键查询该用户的全部优惠券数据
    """
    import hashlib
    # 1. 尝试对手机号进行 MD5 计算以便支持 120 前缀的密文查找
    md5_val = hashlib.md5(mobile.strip().encode('utf-8')).hexdigest()
    
    # 2. 跨库联表查询核心 SQL (jryg_user.users 联表 jryg_coupon.coupon_user_new)
    sql = """
    SELECT 
        u.UserID, 
        u.Mobile, 
        u.NickName,
        c.id AS coupon_id,
        c.coupon_new_id,
        c.coupon_title,
        c.status AS coupon_status,
        c.use_time,
        c.created_at AS coupon_created_at
    FROM jryg_user.users u
    INNER JOIN jryg_coupon.coupon_user_new c ON u.UserID = c.user_id
    WHERE u.Mobile = %s 
       OR u.Mobile = %s 
       OR u.Mobile LIKE CONCAT('%%120', %s);
    """
    with MySQLClient() as client:
        return client.execute_query(sql, (mobile, mobile.strip(), md5_val))


def delete_user_completely(user_id: int):
    """
    完全删除/清退该测试用户的所有账户、微信、以及鉴权绑定信息
    """
    with MySQLClient() as client:
        logger.info(f"🚮 正在开始完全清除 UserID 为 {user_id} 的全部用户数据...")
        # 1. 删除微信关联信息
        client.execute_non_query("DELETE FROM jryg_user.user_weixin_info WHERE user_id = %s;", (user_id,))
        # 2. 删除 OAuth 授权关联信息
        client.execute_non_query("DELETE FROM jryg_user.user_oauth_info WHERE user_id = %s;", (user_id,))
        # 3. 删除主表用户记录
        res = client.execute_non_query("DELETE FROM jryg_user.users WHERE UserID = %s;", (user_id,))
        logger.info(f"🎉 成功完成用户 {user_id} 的彻底清除。")
        return res


def clean_temp_md5_users():
    """
    清理所有以 120% 开头的测试临时用户
    """
    with MySQLClient() as client:
        logger.info("🚮 正在清理所有以 120%% 开头的临时加密测试用户数据...")
        res = client.execute_non_query("DELETE FROM jryg_user.users WHERE Mobile LIKE '120%';")
        return res


def get_user_payscore_bind(user_id: int):
    """
    查询用户的微信支付分绑定记录
    """
    with MySQLClient() as client:
        sql = "SELECT * FROM jryg_user.user_payscore_bind WHERE user_id = %s;"
        return client.execute_query(sql, (user_id,))


def get_user_sesame_contract(user_id: int):
    """
    查询用户的芝麻信用分签约记录
    """
    with MySQLClient() as client:
        sql = "SELECT * FROM jryg_user.user_pay_contract WHERE user_id = %s;"
        return client.execute_query(sql, (str(user_id),))


def delete_all_user_coupons(user_id: int):
    """
    删除一个用户(user_id)的全部优惠券
    """
    with MySQLClient() as client:
        logger.info(f"🚮 正在从数据库删除 UserID: {user_id} 的全部优惠券数据...")
        sql = "DELETE FROM jryg_coupon.coupon_user_new WHERE user_id = %s;"
        return client.execute_non_query(sql, (user_id,))


def insert_payscore_bind(user_id: int, openid: str, appid: str = 'wxe38d5ae955d4362e', service_status: int = 1):
    """
    强制向数据库中插入/绑定微信支付分记录
    """
    sql = """
    INSERT INTO jryg_user.user_payscore_bind (user_id, openid, appid, service_status) 
    VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE openid=%s, appid=%s, service_status=%s;
    """
    with MySQLClient() as client:
        logger.info(f"➕ 正在为用户 {user_id} 绑定微信支付分记录...")
        res = client.execute_non_query(sql, (user_id, openid, appid, service_status, openid, appid, service_status))
        return res


def insert_sesame_contract(user_id: int, agreement_no: str = 'ZMOP99202403090200840076334528', app_id: str = '2021003164647030'):
    """
    强制向数据库中插入/签署芝麻信用分记录
    """
    sql = """
    INSERT INTO jryg_user.user_pay_contract
    (user_id, source, mode, app_id, union_id, open_id, nick_name, agreement_no, invalid_time, status, is_del, created_at, updated_at)
    VALUES (%s, 2, 2, %s, '', '', '', %s, '9999-01-01 00:00:00', 1, 1, NOW(), NOW())
    ON DUPLICATE KEY UPDATE agreement_no=%s, status=1, is_del=1, updated_at=NOW();
    """
    with MySQLClient() as client:
        logger.info(f"➕ 正在为用户 {user_id} 签署芝麻信用分契约记录...")
        res = client.execute_non_query(sql, (user_id, app_id, agreement_no, agreement_no))
        return res


# ==========================================
# ⚙️ 交互式多功能数据库调试控制台
# ==========================================
if __name__ == "__main__":
    import time
    
    # 临时静默底层 logger 打印以确保交互控制台界面极简美观
    import logging
    logging.getLogger("database_system").setLevel(logging.WARNING)

    while True:
        print("\n" + "=" * 65)
        print("  🗄️ 数据库高频工具交互式控制台")
        print("=" * 65)
        print("  [1] 🔍 查询用户信息 (支持手机号 / 120临时MD5号 / 模糊查询)")
        print("  [2] 🎫 查询用户优惠券信息 (按 UserID 查询)")
        print("  [3] 💳 查询用户微信支付分绑定记录")
        print("  [4] 📜 查询用户芝麻信用分签约记录")
        print("  [5] ➕ 强制绑定微信支付分 (写入 user_payscore_bind)")
        print("  [6] ➕ 强制签署芝麻信用分 (写入 user_pay_contract)")
        print("  [7] 🚮 彻底清空并销毁指定测试用户数据 (清理全部绑定和主表)")
        print("  [8] 🚮 清理所有以 120% 开头的测试临时用户")
        print("  [9] 🔌 测试数据库连通状态")
        print("  [10] 🚮 删除用户全部优惠券 (先展示，再确认删除)")
        print("  [11] 🔗 跨库联表查券 (输入手机号一键直出 UserID + 优惠券)")
        print("  [0] 🚪 退出控制台")
        print("=" * 65)
        
        choice = input("👉 请选择您要执行的功能编号: ").strip()
        
        if choice == "1":
            mobile = input("💬 请输入要查询的手机号: ").strip()
            if not mobile:
                print("⚠️ 手机号不能为空！")
                continue
            print(f"正在查询中...")
            try:
                users = get_user_by_mobile(mobile)
                if users:
                    print(f"🎉 成功查到 {len(users)} 条匹配的用户记录：")
                    for idx, u in enumerate(users):
                        print(f"  [{idx + 1}] UserID: {u.get('UserID')} | NickName: {u.get('NickName')} | Mobile: {u.get('Mobile')} | Status: {u.get('Status')} | CreatedAt: {u.get('CreatedAt')}")
                else:
                    print("❌ 未在数据库中查询到匹配的用户数据。")
            except Exception as e:
                print(f"❌ 执行查询时发生错误: {e}")
                
        elif choice == "2":
            uid_str = input("💬 请输入用户的 UserID: ").strip()
            if not uid_str or not uid_str.isdigit():
                print("⚠️ UserID 必须是纯数字！")
                continue
            print(f"正在查询优惠券...")
            try:
                coupons = get_user_coupons(int(uid_str))
                if coupons:
                    print(f"🎉 该用户共持有 {len(coupons)} 张优惠券：")
                    # 按需优雅展示前20条
                    for idx, cp in enumerate(coupons[:20]):
                        print(f"  [{idx + 1}] ID: {cp.get('id')} | CouponNewID: {cp.get('coupon_new_id')} | Title: {cp.get('coupon_title')} | Status: {cp.get('status')} | UseTime: {cp.get('use_time')}")
                    if len(coupons) > 20:
                        print(f"  ... 已折叠剩余 {len(coupons) - 20} 条记录")
                else:
                    print("ℹ️ 该用户当前不持有任何优惠券。")
            except Exception as e:
                print(f"❌ 查询优惠券发生错误: {e}")
                
        elif choice == "3":
            uid_str = input("💬 请输入用户的 UserID: ").strip()
            if not uid_str or not uid_str.isdigit():
                print("⚠️ UserID 必须为纯数字！")
                continue
            try:
                records = get_user_payscore_bind(int(uid_str))
                if records:
                    print(f"🎉 查到 {len(records)} 条微信支付分绑定记录：")
                    for idx, r in enumerate(records):
                        print(f"  [{idx + 1}] ID: {r.get('id')} | AppID: {r.get('appid')} | OpenID: {r.get('openid')} | Status: {r.get('service_status')}")
                else:
                    print("ℹ️ 该用户未绑定微信支付分。")
            except Exception as e:
                print(f"❌ 查询支付分发生错误: {e}")
                
        elif choice == "4":
            uid_str = input("💬 请输入用户的 UserID: ").strip()
            if not uid_str or not uid_str.isdigit():
                print("⚠️ UserID 必须为纯数字！")
                continue
            try:
                records = get_user_sesame_contract(int(uid_str))
                if records:
                    print(f"🎉 查到 {len(records)} 条芝麻分签约记录：")
                    for idx, r in enumerate(records):
                        print(f"  [{idx + 1}] AppID: {r.get('app_id')} | AgreementNo: {r.get('agreement_no')} | Status: {r.get('status')} | IsDel: {r.get('is_del')}")
                else:
                    print("ℹ️ 该用户未签约芝麻信用分。")
            except Exception as e:
                print(f"❌ 查询芝麻分发生错误: {e}")

        elif choice == "5":
            uid_str = input("💬 请输入要绑定的 UserID: ").strip()
            openid = input("💬 请输入微信 OpenID (直接回车默认模拟): ").strip()
            if not uid_str or not uid_str.isdigit():
                print("⚠️ UserID 必须为纯数字！")
                continue
            if not openid:
                openid = "oZq7PjrwYXNdqQs6BnGKrXyXg6Nc"
            try:
                res = insert_payscore_bind(int(uid_str), openid)
                print(f"🎉 微信支付分强制绑定提交成功！受影响行数: {res.get('affected_rows')}")
            except Exception as e:
                print(f"❌ 绑定微信支付分操作失败: {e}")

        elif choice == "6":
            uid_str = input("💬 请输入要签署的 UserID: ").strip()
            if not uid_str or not uid_str.isdigit():
                print("⚠️ UserID 必须为纯数字！")
                continue
            try:
                res = insert_sesame_contract(int(uid_str))
                print(f"🎉 芝麻信用分契约强制签署成功！受影响行数: {res.get('affected_rows')}")
            except Exception as e:
                print(f"❌ 签署芝麻信用分操作失败: {e}")

        elif choice == "7":
            uid_str = input("⚠️【危险危险】请输入要清退销毁的 UserID: ").strip()
            if not uid_str or not uid_str.isdigit():
                print("⚠️ UserID 必须为纯数字！")
                continue
            double_check = input(f"❓ 确认彻底抹去用户 {uid_str} 的全部数据？不可逆！(y/n): ").strip().lower()
            if double_check == 'y':
                try:
                    res = delete_user_completely(int(uid_str))
                    print("🎉 清空并注销该用户账户及关联绑定全部成功！")
                except Exception as e:
                    print(f"❌ 清退用户时发生错误: {e}")
            else:
                print("已安全取消。")

        elif choice == "8":
            double_check = input("❓ 确定清除全部 120% 的临时加密测试用户？(y/n): ").strip().lower()
            if double_check == 'y':
                try:
                    res = clean_temp_md5_users()
                    print(f"🎉 临时用户清除完毕！受影响行数: {res.get('affected_rows')}")
                except Exception as e:
                    print(f"❌ 清理加密临时用户时发生错误: {e}")
            else:
                print("已取消。")
                
        elif choice == "9":
            try:
                with MySQLClient() as client:
                    version_res = client.execute_query("SELECT VERSION() AS version;")
                    if version_res:
                        print(f"✅ 数据库连接通畅！服务器版本: {version_res[0]['version']}")
            except Exception as e:
                print(f"❌ 连接测试失败: {e}")
                
        elif choice == "10":
            uid_str = input("💬 请输入要清空优惠券的 UserID: ").strip()
            if not uid_str or not uid_str.isdigit():
                print("⚠️ UserID 必须为纯数字！")
                continue
            
            user_id = int(uid_str)
            print(f"🔍 正在查询 UserID: {user_id} 的全部优惠券...")
            try:
                coupons = get_user_coupons(user_id)
                if not coupons:
                    print("ℹ️ 该用户当前不持有任何优惠券，无需执行删除。")
                    continue
                
                print(f"🎉 成功查到该用户共持有 {len(coupons)} 张优惠券如下：")
                for idx, cp in enumerate(coupons):
                    print(f"  [{idx + 1}] ID: {cp.get('id')} | CouponNewID: {cp.get('coupon_new_id')} | Title: {cp.get('coupon_title')} | Status: {cp.get('status')} | CreateTime: {cp.get('created_at')}")
                
                # 双重防呆确认
                double_check = input(f"\n⚠️ 确定清空该用户的全部 {len(coupons)} 张优惠券？不可逆！(y/n): ").strip().lower()
                if double_check == 'y':
                    res = delete_all_user_coupons(user_id)
                    print(f"🎉 成功清空用户 {user_id} 的全部优惠券！受影响行数: {res.get('affected_rows')}")
                else:
                    print("已取消删除操作。")
            except Exception as e:
                print(f"❌ 执行删除优惠券操作失败: {e}")
                
        elif choice == "11":
            mobile = input("💬 请输入要查券的手机号: ").strip()
            if not mobile:
                print("⚠️ 手机号不能为空！")
                continue
            print(f"🔍 正在执行【跨库连表】高速检索...")
            try:
                records = get_user_coupons_by_mobile(mobile)
                if records:
                    # 首先提取该手机号对应的 user_id 信息展现给用户
                    first_record = records[0]
                    print(f"✨ 检索成功！")
                    print(f"👤 用户账号信息: UserID: {first_record.get('UserID')} | Mobile: {first_record.get('Mobile')} | NickName: {first_record.get('NickName')}")
                    print(f"🎫 该用户当前共持有 {len(records)} 张优惠券，详情如下：")
                    for idx, r in enumerate(records):
                        print(f"  [{idx + 1}] ID: {r.get('coupon_id')} | CouponNewID: {r.get('coupon_new_id')} | Title: {r.get('coupon_title')} | Status: {r.get('coupon_status')} | CreateTime: {r.get('coupon_created_at')}")
                else:
                    # 如果 INNER JOIN 查不到，有可能是用户存在但当前没有持有任何优惠券。为提升用户体验，进行降级二次确认
                    print("ℹ️ 跨库联表未查到持券记录。正在查询此用户是否存在于用户中心...")
                    user_exist = get_user_by_mobile(mobile)
                    if user_exist:
                        usr = user_exist[0]
                        print(f"👤 用户已找到: UserID: {usr.get('UserID')} | Mobile: {usr.get('Mobile')} | NickName: {usr.get('NickName')}")
                        print("ℹ️ 该用户目前没有持有任何优惠券。")
                    else:
                        print("❌ 数据库中未找到任何匹配的用户记录，且该手机号未注册。")
            except Exception as e:
                print(f"❌ 跨库连表查券操作失败: {e}")
                
        elif choice == "0":
            print("👋 已安全退出数据库高频工具。")
            break
            
        else:
            print("⚠️ 无效的选择，请输入 0-11 范围内的功能数字！")
            
        time.sleep(1)
