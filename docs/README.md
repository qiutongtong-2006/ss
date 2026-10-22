# 学生宿舍报修管理系统

软件工程课程设计　个人独立开发　总工期 3～4 周

系统面向学生、维修人员和宿管三类角色，打通“报修—受理派单—接单维修—完工—验收评价—归档”的完整闭环。

## 技术栈

| 项目 | 版本或工具 |
| --- | --- |
| 开发语言 | Python 3.12.6 |
| Web 框架 | Django 5.2.18 LTS |
| 数据库 | MySQL 8.0.45 |
| 数据库驱动 | mysqlclient 2.3.0 |
| 前端 | Django 模板 + Bootstrap 5 |
| 开发工具 | PyCharm |
| 开发方式 | 个人独立开发，敏捷迭代 |

## 当前进度

- [x] 迭代 0：环境与清单就绪
- [x] 迭代 1：学生注册登录与提交报修
- [x] 迭代 2：宿管受理派单
- [ ] 迭代 3：维修人员接单与维修记录（进行中）
- [ ] 迭代 4：学生验收评价，主闭环打通
- [ ] 迭代 5：权限加固与基础数据
- [ ] 迭代 6：缓冲、缺陷修复与交付

## 文档索引

- [问题定义概述](问题定义概述.md)
- [可行性研究报告](可行性研究报告.md)
- [需求构思](需求构思.md)
- [敏捷开发计划](敏捷开发计划.md)
- [用户故事与 MoSCoW 优先级](用户故事与MoSCoW.md)
- [数据流图与系统流程图说明](数据流图与系统流程图说明.md)
- [迭代 0 完成记录](迭代0-完成记录.md)
- [迭代 1 计划](迭代1-计划.md)
- [迭代 1 完成记录](迭代1-完成记录.md)
- [迭代 2 计划](迭代2-计划.md)
- [迭代 2 完成记录](迭代2-完成记录.md)
- [UI 优化待办](UI优化待办.md)

图表文件：

- `图1-数据流图-顶层图.png` / `.svg`
- `图2-数据流图-0层图.png` / `.svg`
- `图3-系统流程图.png` / `.svg`

## 目录结构

```text
D:\code\ss
├─ manage.py              Django 管理入口
├─ ss\                    项目配置（settings、urls、wsgi）
├─ repair\                业务 app（用户、工单、维修、验收）
├─ templates\             页面模板
├─ docs\                  课程文档与图表
├─ .env                   本地数据库配置，不提交 Git
├─ .venv\                 虚拟环境
└─ .gitignore
```

## 常用命令

```powershell
# 启动开发服务器
.\.venv\Scripts\python.exe manage.py runserver

# 检查项目
.\.venv\Scripts\python.exe manage.py check --database default

# 生成迁移
.\.venv\Scripts\python.exe manage.py makemigrations repair

# 应用迁移
.\.venv\Scripts\python.exe manage.py migrate

# 创建管理员
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## 数据库

- 数据库名：`dorm_repair_django`
- 账号：`dorm_django_user`
- 配置文件：项目根目录 `.env`
- MySQL 服务：`MySQL80`

## 注意事项

1. `.env` 已写入 `.gitignore`，不要提交或公开数据库密码。
2. Django 固定使用 5.2 LTS，因为 Django 6.1 要求 MySQL 8.4 及以上。
3. 旧数据库 `dorm_repair`、`dorm_system` 属于其他项目，不要删除或修改。
4. 每个迭代结束都要留下可运行的系统、自测记录和 Git 提交。
