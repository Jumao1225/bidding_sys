"""
文档切分与双端策略（常规与投标文件）单元测试

测试 ExtractorService 的核心方法：
- _detect_major_chapter_in_line: 各级标题分理识别（通用及标书定制）
- _group_markdown_text_by_chapter: 按 Markdown 正文层级归类大组
- _split_table_preserving_headers: 巨型大表格自动携带表头分割策略
- _adaptive_split_chapter: 章节及复合图表分级处理技巧
"""
import pytest
import os
from app.services.extractor_service import (
    ExtractorService,
    MAX_CHUNK_SIZE,
    CHUNK_OVERLAP,
)


@pytest.fixture
def extractor():
    """创建一个 ExtractorService 实例用于各功能单元测试"""
    return ExtractorService()


# ========== 测试 _detect_major_chapter_in_line ==========

class TestDetectMajorChapterInLine:
    """章节与标书目录层级解析测试"""

    def test_detect_standard_chapter_general(self, extractor):
        """正常情况：标准「第X章」格式于默认状态应当识别成功"""
        result = extractor._detect_major_chapter_in_line("第一章 招标公告", doc_type="general")
        assert result == "第一章 招标公告"

    def test_detect_attachment_format_general(self, extractor):
        """正常情况：标准「附件X」在通用和底表时理应皆为第一大层级"""
        result = extractor._detect_major_chapter_in_line("附件一：核心报价表")
        assert result == "附件一：核心报价表"

    def test_detect_chinese_number_not_major_in_general(self, extractor):
        """常规控制：通用格式中「一、背景」应列入正文小节而非强占首层章头"""
        result = extractor._detect_major_chapter_in_line("一、重点项目概述", doc_type="general")
        assert result is None

    def test_detect_chinese_number_major_in_bid(self, extractor):
        """专项飞升：投标文件 (doc_type='bid') 中「一、商务响应」必须独立判定为显着父级大卷"""
        result = extractor._detect_major_chapter_in_line("一、商务响应以及详细资信情况", doc_type="bid")
        assert result == "一、商务响应以及详细资信情况"

    def test_detect_table_title_major_in_bid(self, extractor):
        """硬核加点：在投书中一表千钧，《核心产品技术参数与响应偏离表》这类应高亮定格大章"""
        result = extractor._detect_major_chapter_in_line("核心设备功能规范及全维度逐条测试偏离表", doc_type="bid")
        assert result == "核心设备功能规范及全维度逐条测试偏离表"

    def test_detect_ignore_noise_subsections_in_bid(self, extractor):
        """核心抗震验证：必须果断抛弃审计报告、财税附录、次级节次与工艺细节里的「伪大章」，杜绝把标书切破！"""
        noises = [
            "四、注册会计师对财务报表审计的责任",
            "二、重要会计政策和会计估计",
            "七、会计报表有关项目注释（单位：人民币元）",
            "十一、其他重要事项",
            "三、会计师事务所营业执照及相关资质",
            "五、满足逆变器技术规范",
            "一、注册会计师执行业务必要时须向委托方出",
            "第一节 屋顶平面布置方案",
            "第二节 安装节点深化做法",
            "第六节 并网柜参数响应",
            "第一节 施工进度计划安排",
            "1．资格证书类别一栏按资格证书填写。",
            "电力工程的施工（资质范围内）",
            "学生吴光平 性别男，一九八三月十三日生，于二〇〇八机电一体化技术",
            "2）加固作业过程按照施工规范要求管控每道工序，每完成一处节点加固，现场技术负责人将开展自检，确认施工参数与设计要求一致后方可进入下一道工序。",
            "验货过程中，逐一核对到场材料的品牌、规格、数量与投标文件及设计要求的一致性，确认所有光伏组件为同一品牌、所有逆变器为同一品牌，满足本次招标的材料一致性要求。"
        ]
        for n in noises:
            res = extractor._detect_major_chapter_in_line(n, doc_type="bid")
            assert res is None, f"不应将内嵌细项目或叙述句 [{n}] 识别为顶级标书大章！"

    def test_detect_true_core_modules_in_bid(self, extractor):
        """火线准入：校验实干性的打分与考核关键总架能顺利立顶为宗师章头"""
        trues = [
            "一、投标函及附加承诺",
            "二、开标一览表（最终报盘）",
            "三、商务条款响应及偏离表",
            "四、技术要求响应及偏离表",
            "2023 年以来类似项目业绩一览表",
            "第九章 投标人基本情况介绍"
        ]
        for t in trues:
            res = extractor._detect_major_chapter_in_line(t, doc_type="bid")
            assert res is not None, f"真正的打分主战大块 [{t}] 被误伤滤除！"


# ========== 测试 _group_markdown_text_by_chapter ==========

class TestGroupMarkdownTextByChapter:
    """自动分组归宗业务层单测"""

    def test_group_general_doc_should_keep_chapters_clean(self, extractor):
        """正常情况：通用文档内连续的多段文字将依从所属前列的第一大章并肩同行"""
        md_text = (
            "前置一些导文\n\n"
            "第一章 项目需求要点\n\n"
            "这里是第一项功能参数描述\n\n"
            "第二章 商务资质审核\n\n"
            "要求具备双证以上体系认证"
        )
        chapters = extractor._group_markdown_text_by_chapter(md_text, doc_type="general")
        assert len(chapters) == 3 # 依次为 默认起始端、第一章、第二章
        assert chapters[1]["title"] == "第一章 项目需求要点"
        assert "第一项功能参数描述" in chapters[1]["text"]

    def test_group_bid_doc_should_split_by_flexible_headers(self, extractor):
        """进阶防御：面向投产长文件只要遇到明确大章表单或中文数字序号加核验件时即独立成大块，而抛弃 1.1 小层级干扰"""
        md_text = (
            "一、报价清单明细\n\n"
            "价格表部分描述……\n\n"
            "二、技术架构体系说明\n\n"
            "该方案采纳全分布式冗余处理。"
        )
        chapters = extractor._group_markdown_text_by_chapter(md_text, doc_type="bid")
        assert len(chapters) >= 2
        assert "一、报价清单明细" == chapters[0]["title"]
        assert "二、技术架构体系说明" == chapters[1]["title"]

    def test_toc_hierarchy_extraction_and_stem_protection(self, extractor):
        """核心硬核单测：校验带有【目录】的投标文件，能够精准建立父子树干，且正文子序号（如（一）短路响应）绝不打断TOC树干！"""
        md_text = (
            "# 投标文件目录\n\n"
            "七、设计方案、服务方案 ............................................ 8\n"
            "    第二章 施工方案说明 ............................................ 12\n"
            "        第一节 施工进度计划安排 ................................... 12\n"
            "        第二节 光伏系统施工工艺流程 ............................. 20\n"
            "八、项目负责人及其他人介绍 ......................................... 35\n\n"
            "# 七、设计方案、服务方案\n\n"
            "## 第二章 施工方案说明\n\n"
            "### 第一节 施工进度计划安排\n\n"
            "## （一）短路响应机制制定\n\n"
            "这里是短路响应机制正文说明……\n\n"
            "## （二）严格遵循短路流程\n\n"
            "这里是严格遵循短路流程正文说明……\n\n"
            "### 第二节 光伏系统施工工艺流程\n\n"
            "#### 一、屋面承载力评估与加固\n\n"
            "这里是屋面承载力评估说明……\n\n"
            "# 八、项目负责人及其他人介绍\n\n"
            "负责人简历如下……"
        )
        chapters = extractor._group_markdown_text_by_chapter(md_text, doc_type="bid")
        
        # 寻找包含（一）短路响应机制制定的块
        chunk_1 = next(c for c in chapters if "（一）短路响应机制制定" in c["title"] or "短路响应" in c["text"])
        assert "七、设计方案、服务方案 > 第二章 施工方案说明" in chunk_1["section_path"]

        # 寻找包含（二）严格遵循短路流程的块
        chunk_2 = next(c for c in chapters if "（二）严格遵循短路流程" in c["title"] or "严格遵循短路流程" in c["text"])
        assert "七、设计方案、服务方案 > 第二章 施工方案说明" in chunk_2["section_path"]

        # 寻找第二节 光伏系统施工工艺流程下面的 一、屋面承载力评估与加固
        chunk_3 = next(c for c in chapters if "屋面承载力" in c["text"])
        assert "七、设计方案、服务方案 > 第二章 施工方案说明" in chunk_3["section_path"]
        assert not chunk_3["section_path"].startswith("（二）")

    def test_user_real_bid_toc_extraction(self, extractor):
        """用户真实目录结构提取测试：确保多层“章/节”已被严格约束为最多两层树干"""
        toc_md = (
            "## 目录\n\n"
            "一、投标函格式....4\n"
            "七、设计方案、服务方案....44\n"
            "第一章 技术参数符合性情况....44\n"
            "第一节 项目概括....44\n"
            "第二节 编制原则....44\n"
            "第二章 根据平面布置等进行评审....56\n"
            "第一节 屋顶平面布置方案....56\n"
            "九、投标人情况介绍....122\n"
            "投标人自有设施设备情况....122\n"
            "投标人获得的相关证书及奖项。....124\n"
            "投标人2023年1月1日以来类似业绩介绍等。....129\n"
            "十、技术要求响应及偏离表....153\n"
        )
        chaps, hierarchy_map = extractor._extract_toc_chapters(toc_md, doc_type="bid")
        
        # 1. 验证常规 1/2 级（最深封顶 2 层）
        assert "一、投标函格式" in chaps
        assert hierarchy_map["第一节 项目概括"] == ["七、设计方案、服务方案", "第一章 技术参数符合性情况"]
        assert hierarchy_map["第一节 屋顶平面布置方案"] == ["七、设计方案、服务方案", "第二章 根据平面布置等进行评审"]

        # 2. 验证“九、投标人情况介绍”下的无序号条目平级替换
        assert hierarchy_map.get("投标人自有设施设备情况") == ["九、投标人情况介绍", "投标人自有设施设备情况"]
        cert_chain = hierarchy_map.get("投标人获得的相关证书及奖项") or hierarchy_map.get("投标人获得的相关证书及奖项。")
        assert cert_chain and cert_chain[0] == "九、投标人情况介绍"
        perf_chain = hierarchy_map.get("投标人2023年1月1日以来类似业绩介绍等") or hierarchy_map.get("投标人2023年1月1日以来类似业绩介绍等。")
        assert perf_chain and perf_chain[0] == "九、投标人情况介绍"

        # 3. 验证回归“十、技术要求响应及偏离表”重置为 L1 顶级
        assert hierarchy_map["十、技术要求响应及偏离表"] == ["十、技术要求响应及偏离表"]




# ========== 测试 _split_table_preserving_headers ==========

class TestSplitTablePreservingHeaders:
    """大型超量清单表格分层保护（首段跟进粘胶机制）验证"""

    def test_short_table_should_remain_unchanged(self, extractor):
        """常规尺寸下的精湛小表不应遭受任一分断破坏"""
        small_table = (
            "| 编号 | 核心部件 | 质保及产地 |\n"
            "| --- | --- | --- |\n"
            "| 01 | 集线网桥 | 五年专厂 |"
        )
        res = extractor._split_table_preserving_headers(small_table, max_size=1200)
        assert len(res) == 1
        assert res[0] == small_table

    def test_long_table_should_carry_headers_to_all_sub_chunks(self, extractor):
        """核心硬杠：当一张天长云展的技术核对单超过切块极限定值，裂断后的每一个续存片段必定自载完整的主列名言！"""
        header = (
            "| 序号 | 系统主项名称 | 参数及性能详细规约（招募标准） | 投标实战自陈及证据指引 | 合同偏差判定 |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
        )
        # 不断自研充实长达20行的厚重大致文块（创造必然超上限局格）
        rows = [f"| 0{i} | 核心高负载处理中枢阵列 | 具备高达99.999%容灾秒变且每秒并发穿透值绝不逊于两百五十万级的承重力。 | 完全顺从指引且我方采用自主多通道均质架构更能超越预期。 | 无偏差，完美符合 |" for i in range(1, 25)]
        full_big_table = header + "\n".join(rows)

        chunks = extractor._split_table_preserving_headers(full_big_table, max_size=1200)
        assert len(chunks) > 1, "超千字豪情长表理应解剖至不同段位内载中"
        
        for c in chunks:
            assert "| 序号 | 系统主项名称 |" in c, "分断出来的任何后续散件理所应当带有这行神圣的主键定义首头！"
            assert "| :--- |" in c


# ========== 测试 _adaptive_split_chapter ==========

class TestAdaptiveSplitChapter:
    """实际大段文字打分发包及分切全维保障"""

    def test_split_short_chapter_produces_single(self, extractor):
        """短款章节一步成型，不添乱发无聊杂碎短签"""
        ch = {
            "title": "（一）合法性验证承诺",
            "text": "本单位对于所供资料的全面真实准确性负终身全额责无旁贷法律义务。",
            "page_start": 2,
            "content_type": "chapter_block",
            "trace_info": {"chapter": "（一）合法性验证承诺", "headings": ["（一）合法性验证承诺"], "element_label": "text"}
        }
        docs = extractor._adaptive_split_chapter(ch, start_index=0)
        assert len(docs) == 1
        assert docs[0].metadata["section_title"] == "（一）合法性验证承诺"

    def test_split_long_chapter_with_tables(self, extractor):
        """交错情态实测：文字夹持漫长列表再继承随从语话，保证结构完整有力不缺行不过幅"""
        prefix = "前置叙事陈词精进……\n\n" * 150
        table_content = (
            "| 代次 | 分类模块 | 参数状态 |\n"
            "| --- | --- | --- |\n"
            "| 一批 | 全栈加速内核 | 标称达标 |\n"
        )
        suffix = "\n\n后缀归总结语与盖章鉴别……" * 150
        ch = {
            "title": "第四篇章 高阶能力评估方案",
            "text": prefix + table_content + suffix,
            "page_start": 8,
            "content_type": "chapter_block",
            "trace_info": {"chapter": "第四篇章 高阶能力评估方案", "headings": [], "element_label": "text"}
        }
        docs = extractor._adaptive_split_chapter(ch, start_index=10)
        assert len(docs) > 1
        
        # 定位包含了真正数据明细的列表那处快览，确保不散伙、不缺半边天
        table_docs = [d for d in docs if "| 代次 |" in d.page_content]
        assert len(table_docs) >= 1
        for td in table_docs:
            assert "全栈加速内核" in td.page_content
