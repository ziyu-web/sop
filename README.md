# 海康互联固件升级工具

基于海康互联开放平台的 Windows 桌面工具，用于批量添加设备、执行多轮固件升级、实时查看进度并导出结果报表。

## 功能

- 批量读取 Excel 设备列表
- 批量添加设备并查询设备信息
- 支持多轮升级和不同升级包
- 实时显示升级状态、进度和日志
- 自动导出 Excel 升级报表

## 安装与启动

需要 Python 3.9+：

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m hikiot.firmware_upgrade_main
```

## Excel 格式

每行一台设备，列顺序如下：

| 列 | 内容 | 必填 |
|---|---|---|
| A | 设备序列号 | 是 |
| B | 验证码 | 是 |
| C | 升级包 1（URL 或本地路径） | 是 |
| D | 升级包 2（可选） | 否 |

## 注意事项

- 使用前请配置海康互联开放平台账号信息。
- 请勿提交或公开 `hikiot/config/default_credentials.json`。
- 升级结果默认保存到 `data/report/`。
