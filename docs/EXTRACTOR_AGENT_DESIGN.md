# 拆解智能体 (Extractor Agent) 设计与实现规划

作为整个智能投标系统的“数据基石”，Extractor Agent 的主要职责是将非结构化的长篇标书（PDF/Word），高保真地转化为带有元数据的结构化文本块，并存入向量数据库，为后续的排雷、算分和写标书等下游 Agent 提供高质量的上下文（Context）。

## 1. 核心挑战与架构设计

解析标书并非简单的“提取文本”，最大的难点在于**版面复杂**和**超长文本切分**。Extractor Agent 必须具备以下核心能力：

### 1.1 多模态解析能力 (特别是表格处理)
标书中最有价值的信息（如打分标准、报价清单、资质要求）通常以复杂的跨页表格形式存在。
*   **普通文本解析**：保留段落顺序，去除页眉页脚等干扰信息。
*   **表格解析策略**：
    *   **方案 A (传统方案)**：使用 `pdfplumber` 或 `PyMuPDF` 解析纯文本表格，转为 Markdown 格式。速度快，但对无边框或跨页表格容易出错。
    *   **方案 B (AI 多模态增强 - 推荐)**：引入 `LlamaParse` 或通过大模型 Vision API，将含有复杂表格的页面先转为图片，由大模型直接“看图”输出精确的 Markdown/HTML 格式表格数据。

### 1.2 语义切片策略 (Semantic Chunking)
粗暴的按字数切分（如每 500 字切一块）会切断完整的规则条款，导致 RAG 检索失败。
*   **基于标题树的切分**：Extractor 需要识别出 PDF 的大纲级别（第一章、1.1节），按自然段落或逻辑章节进行切分。
*   **重叠窗口 (Overlap)**：在切分时设置一定的重叠（如 Chunk 长度 800，重叠 100），确保跨段落的上下文连贯。

### 1.3 核心元数据注入 (Metadata Tagging)
为了实现“点击高亮溯源”并提高检索精准度，Extractor 提取出的每一个 Chunk（文本块）必须附带丰富的 Metadata，写入 `DOC_CHUNK` 表：
*   `document_id`: 所属标书。
*   `page_num`: 原始页码（前端溯源必备）。
*   `section_title`: 所属章节（如“评标办法”）。
*   `content_type`: 标识该块是纯文本（text）还是表格（table）。

### 1.4 Word 文档 (.doc / .docx) 的特殊处理
虽然 PDF 是招投标中最常见的格式，但系统同样需要完全兼容 Word 格式的原文件解析：
*   **格式统一化**：对于早期的 `.doc` 格式，系统在上传后的预处理阶段，可通过后台调用 LibreOffice (Headless 模式) 自动将其转换为 `.docx`，以便底层统一处理。
*   **解析优势与差异**：与 PDF（偏向视觉坐标排版）不同，`.docx` 文件的本质是结构化的 XML 归档（如你的项目环境中的 `docx` skill 描述的那样）。这意味着在处理 Word 时，我们可以**极其精准地提取出原生的表格结构 (Tables)** 和**大纲级别 (Heading Levels)**，完全不用担心像 PDF 那样发生“跨页表格乱码”或“边框粘连”的问题。
*   **溯源逻辑差异**：Word 文档的特点是**没有绝对的物理页码**（页码受不同电脑的渲染引擎或纸张设置影响）。因此，Word 提取的 Chunk，其 Metadata 中的溯源锚点将弱化 `page_num`，而强化 `section_title`（章节名称）或内部的 `Bookmark` / 段落 ID，以实现前端的精准跳转。

---

## 2. 推荐的技术栈选型

| 模块功能 | 推荐技术栈 | 理由 |
| :--- | :--- | :--- |
| **基础文本解析 (PDF)** | **PyMuPDF (fitz)** 或 **pdfplumber** | Python 生态中最成熟、速度最快的 PDF 解析库。 |
| **基础文本解析 (Word)** | **python-docx** 或 **unstructured** | 能直接读取 `.docx` 的原生 XML 树，完美保留多级标题与原生表格。配合 LibreOffice 可兼容 `.doc`。 |
| **复杂/扫描件表格解析** | **LlamaParse** 或 **阿里/腾讯 OCR API** | 专门针对复杂文档解析优化的 AI 级工具，能完美还原 Markdown 表格。 |
| **语义切片 (Chunking)** | **LangChain** (`RecursiveCharacterTextSplitter`) | 开箱即用，支持基于分隔符（如 `\n\n`, `\n`）的智能切分。 |
| **向量化 (Embedding)** | **BGE-m3** 或 **OpenAI text-embedding-3** | 目前开源及商业模型中支持多语言且检索精度极高的 Embedding 模型。 |

---

## 3. 工作流伪代码演示 (Pipeline)

Extractor Agent 的执行流通常是一个后台异步任务（Celery Task），因为解析上百页的 PDF 可能耗时数分钟。

```python
def run_extractor_agent(document_path: str, document_id: str):
    # 1. 版面分析与内容提取
    pages = pdf_parser.extract_pages(document_path)
    
    chunks_to_save = []
    
    for page in pages:
        # 如果当前页包含复杂表格，调用增强 AI 解析
        if page.has_complex_table():
            markdown_content = ai_vision_parser.extract_table_as_markdown(page)
            content_type = "table"
        else:
            markdown_content = page.get_text()
            content_type = "text"
            
        # 2. 语义切片
        sub_chunks = semantic_splitter.split_text(markdown_content)
        
        # 3. 封装 Metadata
        for chunk_text in sub_chunks:
            chunk = DocChunk(
                document_id=document_id,
                content=chunk_text,
                page_num=page.number,
                section_title=page.get_nearest_header(),
                content_type=content_type
            )
            chunks_to_save.append(chunk)
            
    # 4. 批量向量化并存入数据库 (PGVector/Milvus)
    vector_db.batch_insert_chunks(chunks_to_save)
    
    return {"status": "success", "total_chunks": len(chunks_to_save)}
```

## 4. 架构决策：为何必须先做拆解和 RAG，而不是直接传全文给大模型？

尽管现在的国产大模型（如 Kimi、DeepSeek）支持百万级超长上下文，但在严肃的招投标系统中，我们**不能直接把 100 页标书丢给大模型排雷**，原因如下：

1. **致命的“中间注意力丢失”（Lost in the Middle）**：大模型对长文档中间部分的记忆会衰减。风险条款往往藏在标书中间，直接传全文极大概率会导致“漏报”，这对于风控是灾难性的。而 RAG 每次只给大模型最相关的几千字，专注度 100%，杜绝漏判。
2. **无法实现精准溯源（Traceability）**：用户需要核实风险条款在原文件的哪一页。全文丢给大模型极易产生页码幻觉；而通过 Extractor 提前切片，每个 Chunk 绑定了真实的 `page_num`，前端可以实现精准的“点击高亮跳转”。
3. **高昂的成本与极慢的响应**：每次排雷、算分、写标书都重读 10 万字，首字响应时间（TTFT）极长且 Token 成本不可控。一次拆解入库后，后续查询成本几乎为零。
4. **外挂规则库容量受限**：大模型的脑容量有限，如果被 10 万字标书占满，就很难再完美结合公司历史积累的《避坑指南》进行双向比对。

因此，Extractor Agent 的“切片入库”是整个系统兼顾**高准确率、低成本、高溯源性**的唯一解。

---

## 5. 下一步行动建议
如果你同意这个设计方案，下一步我们将进入**技术验证阶段（PoC）**。建议我们编写一个独立的 Python 脚本，拿一份真实的 PDF 标书进行解析和切片测试，验证所选工具（如 PyMuPDF 或 LlamaParse）能否完美提取出标书中的打分表格。
