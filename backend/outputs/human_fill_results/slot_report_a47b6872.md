# 拟人化 Agent 标书槽位解析与填报报告

- **文档 ID**: `a47b6872-9600-4b30-abcb-4bf3692ec9ae`
- **Task ID**: `task_1785141720`
- **耗时**: `45007 ms`
- **识别槽位总数**: `55` | **成功填报**: `55`

## 大模型总体分析
本文档包含大量需要投标人填写的空白槽位，主要集中在封面（项目名称、招标编号、投标人名称、日期），投标函（招标编号、签字人、公司名称、通讯地址等），开标一览表（总价和报价大写），授权委托书（委托人、受托人、法定代表人等），各类承诺书（单位名称、日期），以及多个表格（分项报价表、耗材表、实质性要求响应表、人员表、技术/商务偏离表）。关键字段包括公司名称、法定代表人、授权代表、项目编号、总价、工期等。建议投标人仔细核对所有空白处，避免遗漏。

## 详细填报对照表

| 序号 | 物理 Path | 前导 Label | 业务 Intent | 数据库直查结果 | 状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `/body/p[35]` | `根据贵方的` | `project_code` | `SZDZ-2026-NG008号` | ✅ success |
| 2 | `/body/p[35]` | `正式授权下述签字人` | `authorized_delegate` | `李四` | ✅ success |
| 3 | `/body/p[35]` | `（姓名和职务）` | `authorized_delegate` | `李四` | ✅ success |
| 4 | `/body/p[35]` | `代表我方` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 5 | `/body/p[35]` | `（投标人的名称）` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 6 | `/body/p[39]` | `地    址：` | `registered_address` | `四川省成都市高新区天府大道北段128号` | ✅ success |
| 7 | `/body/p[40]` | `邮    编：` | `contact_phone` | `028-85123456` | ✅ success |
| 8 | `/body/p[41]` | `电    话：` | `contact_phone` | `028-85123456` | ✅ success |
| 9 | `/body/p[42]` | `传    真：` | `contact_phone` | `028-85123456` | ✅ success |
| 10 | `/body/p[43]` | `投标单位代表姓名（签字）：` | `authorized_delegate` | `李四` | ✅ success |
| 11 | `/body/p[44]` | `投标单位名称：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 12 | `/body/p[45]` | `公    章：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 13 | `/body/p[46]` | `日    期：` | `construction_period` | `接到采购人进场通知后60日内完成全容量并网发电并通过供电公司验收（发电计量表安装完成及低压并网各项手续完成）` | ✅ success |
| 14 | `/body/p[48]` | `投标人全称（加盖公章）：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 15 | `/body/p[49]` | `法定代表人或授权代表签字（或盖章）：` | `legal_representative` | `张三` | ✅ success |
| 16 | `/body/tbl[1]/tr[2]/tc[3]` | `总价（元）` | `bid_price_numeric` | `967840.36` | ✅ success |
| 17 | `/body/tbl[1]/tr[2]/tc[4]` | `备注` | `bid_price_numeric` | `967840.36` | ✅ success |
| 18 | `/body/tbl[1]/tr[3]/tc[2]` | `投标总报价（大写）` | `bid_price_chinese` | `玖拾陆万柒仟捌佰肆拾元叁角陆分` | ✅ success |
| 19 | `/body/p[51]` | `委托人：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 20 | `/body/p[52]` | `地址：` | `registered_address` | `四川省成都市高新区天府大道北段128号` | ✅ success |
| 21 | `/body/p[52]` | `法定代表人：` | `legal_representative` | `张三` | ✅ success |
| 22 | `/body/p[53]` | `受托人：` | `authorized_delegate` | `李四` | ✅ success |
| 23 | `/body/p[53]` | `性别：` | `authorized_delegate` | `李四` | ✅ success |
| 24 | `/body/p[54]` | `所在单位：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 25 | `/body/p[55]` | `职务：` | `authorized_delegate` | `李四` | ✅ success |
| 26 | `/body/p[55]` | `联系方式：` | `contact_phone` | `028-85123456` | ✅ success |
| 27 | `/body/p[56]` | `兹委托受托人` | `authorized_delegate` | `李四` | ✅ success |
| 28 | `/body/p[56]` | `合法地代表我单位参加` | `authorized_delegate` | `李四` | ✅ success |
| 29 | `/body/p[56]` | `组织的` | `project_name` | `和烁热能公司屋顶（400kW）分布式光伏发电项目` | ✅ success |
| 30 | `/body/p[59]` | `委托单位（公章）：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 31 | `/body/p[61]` | `法定代表人（签章）：` | `legal_representative` | `张三` | ✅ success |
| 32 | `/body/p[63]` | `日      期：` | `construction_period` | `接到采购人进场通知后60日内完成全容量并网发电并通过供电公司验收（发电计量表安装完成及低压并网各项手续完成）` | ✅ success |
| 33 | `/body/p[65]` | `投标单位（公章）：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 34 | `/body/p[67]` | `日       期：` | `construction_period` | `接到采购人进场通知后60日内完成全容量并网发电并通过供电公司验收（发电计量表安装完成及低压并网各项手续完成）` | ✅ success |
| 35 | `/body/p[69]` | `投标单位（签章）：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 36 | `/body/p[70]` | `日期：` | `construction_period` | `接到采购人进场通知后60日内完成全容量并网发电并通过供电公司验收（发电计量表安装完成及低压并网各项手续完成）` | ✅ success |
| 37 | `/body/tbl[2]` | `序号1-18行（所有数据行）` | `bid_price_numeric` | `967840.36` | ✅ success |
| 38 | `/body/tbl[2]/tr[19]/tc[2]` | `大写：` | `bid_price_chinese` | `玖拾陆万柒仟捌佰肆拾元叁角陆分` | ✅ success |
| 39 | `/body/p[72]` | `交货期限：` | `construction_period` | `接到采购人进场通知后60日内完成全容量并网发电并通过供电公司验收（发电计量表安装完成及低压并网各项手续完成）` | ✅ success |
| 40 | `/body/tbl[3]` | `常用零件表后几行` | `bid_price_numeric` | `967840.36` | ✅ success |
| 41 | `/body/tbl[4]/tr[2]/tc[2]` | `实质性要求内容` | `qualification_cert` | `[待手动补充资质证书: 实质性要求内容]` | ✅ success |
| 42 | `/body/tbl[4]/tr[2]/tc[3]` | `是否响应` | `qualification_cert` | `[待手动补充资质证书: 是否响应]` | ✅ success |
| 43 | `/body/tbl[4]/tr[3]/tc[2]` | `实质性要求内容` | `qualification_cert` | `[待手动补充资质证书: 实质性要求内容]` | ✅ success |
| 44 | `/body/tbl[4]/tr[3]/tc[3]` | `是否响应` | `qualification_cert` | `[待手动补充资质证书: 是否响应]` | ✅ success |
| 45 | `/body/tbl[4]/tr[4]/tc[2]` | `实质性要求内容` | `qualification_cert` | `[待手动补充资质证书: 实质性要求内容]` | ✅ success |
| 46 | `/body/tbl[4]/tr[4]/tc[3]` | `是否响应` | `qualification_cert` | `[待手动补充资质证书: 是否响应]` | ✅ success |
| 47 | `/body/tbl[5]` | `项目负责人表格数据行` | `qualification_cert` | `[待手动补充资质证书: 项目负责人表格数据行]` | ✅ success |
| 48 | `/body/tbl[6]` | `技术要求响应表数据行` | `qualification_cert` | `[待手动补充资质证书: 技术要求响应表数据行]` | ✅ success |
| 49 | `/body/tbl[7]` | `商务条款响应表数据行` | `qualification_cert` | `[待手动补充资质证书: 商务条款响应表数据行]` | ✅ success |
| 50 | `/body/p[75]` | `投标人全称（加盖公章）：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 51 | `/body/p[76]` | `法定代表人或授权代表签字（或盖章）：` | `legal_representative` | `张三` | ✅ success |
| 52 | `/body/p[78]` | `投标单位（加盖公章）：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 53 | `/body/p[79]` | `年   月   日` | `construction_period` | `接到采购人进场通知后60日内完成全容量并网发电并通过供电公司验收（发电计量表安装完成及低压并网各项手续完成）` | ✅ success |
| 54 | `/body/p[80]` | `投标单位（加盖公章）：` | `company_name` | `四川石楠建设工程有限公司` | ✅ success |
| 55 | `/body/p[81]` | `年   月   日` | `construction_period` | `接到采购人进场通知后60日内完成全容量并网发电并通过供电公司验收（发电计量表安装完成及低压并网各项手续完成）` | ✅ success |
