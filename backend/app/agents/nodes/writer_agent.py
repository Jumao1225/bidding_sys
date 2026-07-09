from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io

class WordGenerator:
    """
    负责将 AI 提取和生成的投标书大纲转换为实际的 Word 文档
    """

    @staticmethod
    def generate_bidding_draft(project_name: str, analysis_results: dict) -> bytes:
        """
        生成一个基础的投标书草稿字节流
        """
        doc = Document()
        
        # 设置标题
        title = doc.add_heading(f"{project_name} - 投标文件草稿", 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        doc.add_paragraph("本草稿由 AI 智能生成，请在此基础上补充详细内容。\n").alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # 第一部分：资质响应
        doc.add_heading("第一部分：资质证明文件", level=1)
        doc.add_paragraph("对照招标文件的核心要求，我方完全响应以下资质：")
        
        if "qualifications" in analysis_results:
            for item in analysis_results["qualifications"].get("items", []):
                doc.add_paragraph(f"✓ {item['requirement']} - {item['status']}", style='List Bullet')
                
        # 第二部分：商务报价
        doc.add_heading("第二部分：商务报价方案", level=1)
        doc.add_paragraph("根据测算，本项目初步报价清单如下：")
        
        if "cost" in analysis_results:
            table = doc.add_table(rows=1, cols=3)
            table.style = 'Table Grid'
            hdr_cells = table.rows[0].cells
            hdr_cells[0].text = '物品名称'
            hdr_cells[1].text = '数量'
            hdr_cells[2].text = '参考小计'
            
            for item in analysis_results["cost"].get("items", []):
                row_cells = table.add_row().cells
                row_cells[0].text = item['name']
                row_cells[1].text = str(item['qty'])
                row_cells[2].text = str(item['subtotal'])

        # 第三部分：风险说明
        doc.add_heading("第三部分：风险与偏离说明", level=1)
        if "risks" in analysis_results:
            for risk in analysis_results["risks"]:
                doc.add_paragraph(f"⚠️ {risk['risk_type']}: {risk['content']}")
        
        # 保存到内存字节流
        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)
        
        return file_stream.getvalue()
