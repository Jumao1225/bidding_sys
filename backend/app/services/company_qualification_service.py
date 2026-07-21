import os
import uuid
import shutil
import base64
import json
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from loguru import logger
from datetime import date
from datetime import date, datetime
import uuid
from openai import OpenAI
from app.db.crud.qualification import qualification_crud
from app.schemas.qualification import QualificationCreate, QualificationExtractionResult, QualificationResponse
from app.services.parsers.mineru_parser import mineru_parser
from app.services.llm_service import llm_service
from app.core.config import settings

class CompanyQualificationService:
    def __init__(self):
        # 确定基础目录路径 (指向 backend 目录)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.upload_dir = os.path.join(base_dir, "uploads", "qualifications")
        os.makedirs(self.upload_dir, exist_ok=True)

    def upload_and_parse(self, db: Session, file: UploadFile, tenant_id: str):
        # 1. 将上传的文件保存到本地磁盘
        file_ext = os.path.splitext(file.filename)[1] if file.filename else ".pdf"
        unique_id = str(uuid.uuid4())
        file_name = f"{unique_id}{file_ext}"
        file_path = os.path.join(self.upload_dir, file_name)

        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            logger.error(f"Failed to save qualification file: {e}")
            raise HTTPException(status_code=500, detail="保存文件失败")

        # 生成用于前端访问的相对路径 URL
        file_url = f"/uploads/qualifications/{file_name}"

        # 2. 判断是否为图片，如果是图片，则使用 VLM 双引擎直接解析
        if file_ext.lower() in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
            logger.info(f"检测到图片文件 {file_name}，将使用 VLM 直接解析")
            return self._parse_image_via_vlm(db, file_path, file_url, tenant_id)

        # 3. 使用 MinerU 解析文档（支持扫描版 PDF 与 OCR）
        logger.info(f"开始使用 MinerU 对 {file_name} 进行 OCR 解析")
        markdown_content = ""
        try:
            # 使用 MinerU 的默认解析模式 (vlm)
            parse_result = mineru_parser.parse(file_path, task_id=unique_id)
            markdown_content = parse_result.get("markdown_content", "")
        except Exception as e:
            logger.error(f"MinerU parsing failed: {e}")
            # 发生异常时记录错误日志，并向用户抛出警告。此处不做强制阻断，而是交由后续的备用方案处理。
            logger.warning("MinerU 提取失败。如果是原生 PDF，后续将使用 PyMuPDF 降级处理。")

        # 3. 大模型信息提取
        if not markdown_content:
            # 如果 MinerU 失败或未配置，降级使用 PyMuPDF 提取原生 PDF 文本
            import fitz
            try:
                doc = fitz.open(file_path)
                for page in doc:
                    markdown_content += page.get_text() + "\n"
            except Exception as fe:
                logger.error(f"Fallback PyMuPDF extraction failed: {fe}")

        if not markdown_content.strip():
            # 如果依然为空，说明可能是扫描版 PDF 且 MinerU 解析失败
            raise HTTPException(status_code=400, detail="无法从文档中提取到有效文本，请确认是否配置了MinerU Token或文件是否损坏。")

        prompt = f"""
        请从以下资质证明文件的内容中提取关键信息。
        注意：
        1. 该文件中可能包含多个独立的不同资质，请务必找出【所有】独立的资质，并将它们作为一个列表返回。
        2. 特别注意：如果有《安全生产许可证》，请务必将其作为一个独立的资质提取出来！绝不能遗漏！
        3. 特别注意：如果是像《建筑业企业资质证书》这样一张证书上印有多个分类项（如：建筑工程总承包二级、环保工程专业承包二级等），【请务必将每一个分类项作为一个独立的资质提取】！资质名称填为该分类（如‘建筑工程施工总承包’），资质等级填为该分类的等级（如‘二级’）。绝对不要把所有的分类都拼接成一个长字符串塞到 level 里！
        4. **公司主体鉴别规则**：证书上可能同时存在“被认证方/持证方”和“发证机关/认证机构（盖章处）”两个公司名称。请务必提取的是**“被认证的公司主体”**（例如：XXX建筑工程有限公司），绝不能误提取发证机构（如：某某认证中心、某某局、某某管理体系认证有限公司）！如果多项资质同属一家公司，请为每一项都填上该持证公司的名称。
        5. 要求严格按照 schema 提取，不要胡编乱造。如果某些信息确实找不到，请置空。
        6. **数量核对规则（防止截断）**：无论原文中有多少条资质（例如即使有N条甚至更多），你必须不厌其烦地一条一条全部提取出来！绝不允许在提取到某一条时擅自停止或省略最后几条！必须保证提取列表的长度与原文中实际的资质条目总数严格一致。
        7. **日期格式强制规范**：提取的 `expiry_date` 必须严格转换为 `YYYY-MM-DD` 格式（使用中划线，如 `XXXX-XX-XX`）。绝不允许出现斜杠（如 `XXXX/XX/XX`）或中文（如 `XXXX年XX月XX日`）。如果是“长期”或无明确日期请直接返回 `null`。
        8. **到期时间精准提取规则**：很多证书（特别是体系认证）上印有多个日期。请务必寻找“有效期至”、“有效期限”、“证书有效期”等明确表示**最终作废**的日期！绝不能误把“发证日期”、“初次获证日期”或“监督审核截止日期”当作到期时间！如果是一个日期范围（如 XXXX-XX-XX 至 YYYY-YY-YY），请只提取**结束日期**。
        9. **资质名称鉴别规则 (防业务范围误导)**：请务必提取证书正上方最醒目的大字标题（如《安全生产许可证》、《质量管理体系认证证书》、《承装（修、试）电力设施许可证》）或具体的资质类别（如“建筑工程施工总承包”）。绝不能把“业务范围”、“许可范围”或“认证范围”（例如：“XXX工程的施工”、“可承担YYY工程”）当作资质名称提取！
        
        【重要示例】
        假设原文有一张“某某资质证书”，写着公司名是“某某公司”，类目包括“某某工程”。
        你需要返回 1 个独立资质：
        [
          {{ "name": "某某工程", "company_name": "某某公司", "level": "二级" }}
        ]

        文档内容:
        {markdown_content}
        """

        try:
            extracted_data_result = llm_service.generate_structured_output(prompt, QualificationExtractionResult)
            extracted_list = extracted_data_result.qualifications
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            raise HTTPException(status_code=500, detail="AI提取信息失败")

        if not extracted_list:
            raise HTTPException(status_code=400, detail="未从文件中识别到任何有效的资质信息")

        # 4. 组装前端所需的对象，不保存到数据库
        mock_objs = []
        for extracted_data in extracted_list:
            qual_name = extracted_data.name if extracted_data.name else "未命名资质"
            
            # 使用临时 UUID 作为前台渲染的 key
            temp_id = "temp_" + uuid.uuid4().hex
            now = datetime.utcnow()
            
            mock_obj = QualificationResponse(
                id=temp_id,
                tenant_id=tenant_id,
                name=qual_name,
                company_name=extracted_data.company_name,
                level=extracted_data.level,
                expiry_date=extracted_data.expiry_date,
                file_url=file_url,
                created_at=now,
                updated_at=now
            )
            mock_objs.append(mock_obj)
        
        return mock_objs

    def _parse_image_via_vlm(self, db: Session, file_path: str, file_url: str, tenant_id: str):
        try:
            with open(file_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"读取图片文件失败: {e}")
            raise HTTPException(status_code=500, detail="读取图片文件失败")

        provider = settings.VLM_PROVIDER
        if provider == "ali":
            api_base = settings.ALI_VLM_API_BASE
            api_key = settings.ALI_VLM_API_KEY
            model_name = settings.ALI_VLM_MODEL_NAME
        else:
            api_base = settings.LOCAL_VLM_API_BASE
            api_key = settings.LOCAL_VLM_API_KEY
            model_name = settings.LOCAL_VLM_MODEL_NAME

        if not api_key:
            raise HTTPException(status_code=500, detail=f"未配置 {provider} 的 VLM API_KEY")

        client = OpenAI(base_url=api_base, api_key=api_key)

        schema_json = '''
        {
          "qualifications": [
            {
              "name": "证书或资质名称（如：安全生产许可证、营业执照）",
              "company_name": "所属公司名称（如：某某建筑工程有限公司）",
              "level": "资质等级（如：一级、特级。如果原文没有明确说明等级或不知道，请统一填 '无'）",
              "expiry_date": "到期时间，格式 YYYY-MM-DD。如果无明确日期请直接填 null，严禁自行编造或推延日期！"
            }
          ]
        }
        '''
        prompt = f"""请从提供的文档图片中提取关键信息。

【提取要求】
0. **【最高指令：零容忍幻觉】你提取的每一个资质名称、等级和日期，必须是图片中清清楚楚、原原本本印着的文字！严禁利用大模型自身的互联网常识或行业习惯进行任何补全、推断或编造（例如自行脑补图片上没有的“冶金工程”、“环保工程”等分类）。如果图片上没有这个字，强制不提取、置空或直接丢弃！**
1. 该文件中可能包含多个独立的不同资质，请务必找出【所有】独立的资质。如果是一张许可证（如安全生产许可证、承装电力设施许可证等），也要当做一项资质进行提取。
2. 特别注意：如果是一张证书（如《建筑业企业资质证书》）上印有多个分类项，【请务必将每一个分类项作为一个独立的资质提取】！资质名称填为该分类（如‘建筑工程施工总承包’），资质等级填为该分类的等级（如‘二级’）。绝对不要把所有的分类都当作一个资质！
3. **公司主体鉴别规则**：证书上通常会同时印有“被认证方/持证方”和“发证机关/认证机构（盖章处）”两个公司名称。请务必识别且只提取**“被认证的公司主体”**（例如：XXX建筑工程有限公司），绝不能误把发证/认证机构（如：某某认证中心、某某局、某某认证股份有限公司）当作所属公司提取出来！即使它在图片的不同位置，也必须准确鉴别并提取出真正的持证方。
4. 严格按照 schema 提取，如果没有找到明确信息，请置空。
5. **信息继承规则**：如果拆分出的多个资质属于同一张证书，它们的“所属公司名称”和“有效截止日期”通常是完全相同的。请务必为拆分出的【每一个】资质都完整拷贝填上公司名称和截止日期，绝对不允许只填第一个而把后面的置空！
6. **等级分离规则**：请务必死死盯住每一个分类项名称后缀的等级字眼（如：一级、二级、三级、特级、甲级、乙级、不分等级等），必须将其与名称剥离开并填入 `level` 字段，严禁漏提任何一项的等级！
7. **全量扫描规则（防漏提）**：请从上到下、逐字逐句地扫描图片中的每一行文字！资质分类项通常会带有序号（如 1、2、3、4... 或者 ①、②、③...）。请仔细清点序号，确保找齐**所有**的资质分类，绝对不能漏掉最后一个或中间的任何一个！
8. **数量核对规则（防止截断）**：无论原图中有多少条资质，你必须不厌其烦地一条一条全部提取出来！绝不允许在提取到某一条时擅自停止或省略最后几条！必须保证提取列表的长度与图片中实际的资质条目总数严格一致。
9. **日期格式强制规范**：提取的 `expiry_date` 必须严格转换为 `YYYY-MM-DD` 格式（使用中划线，如 `XXXX-XX-XX`）。绝不允许出现斜杠（如 `XXXX/XX/XX`）或中文（如 `XXXX年XX月XX日`）。如果是“长期”或无明确日期请直接返回 `null`。
10. **到期时间精准提取规则**：很多证书（特别是环境、质量等体系认证）上印有多个日期。请务必寻找“有效期至”、“有效期限”、“证书有效期”等明确表示**最终作废**的日期！绝不能误把“发证日期”、“初次获证日期”或“监督审核截止日期”当作到期时间！如果是一个日期范围（如 XXXX-XX-XX 至 YYYY-YY-YY），请只提取**结束日期**。
11. **资质名称鉴别规则 (防业务范围误导)**：请务必提取证书正上方最醒目的大字标题（如《安全生产许可证》、《质量管理体系认证证书》、《承装（修、试）电力设施许可证》）或具体的资质类别（如“建筑工程施工总承包”）。绝不能把“业务范围”、“许可范围”或“认证范围”（例如：“XXX工程的施工”、“可承担YYY工程”）当作资质名称提取！

【重要示例】
假设图片是一张“某某资质证书”，写着公司名是“某某公司”，类目包括“某某工程”。
你需要返回包含 1 个独立资质的列表：
{{
  "qualifications": [
    {{ "name": "某某工程", "company_name": "某某公司", "level": "二级" }}
  ]
}}

【强制格式约束】
必须返回严格符合以下 JSON Schema 的纯 JSON 格式：
{schema_json}

[极其重要]
1. 只能输出纯 JSON 数据，绝对不要用 ```json 标签包裹！
2. 确保所有的双引号、括号、逗号等符号完美匹配，不允许出现任何语法错误。
"""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]
            }
        ]

        logger.info(f"正在向 {provider} VLM ({model_name}) 发送图片解析请求...")
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.1,
            )
            result = response.choices[0].message.content
        except Exception as e:
            logger.error(f"VLM 请求失败: {e}")
            raise HTTPException(status_code=500, detail="VLM 图片解析失败")

        # 解析 JSON 剥除 Markdown 标签
        clean_result = result.strip()
        if clean_result.startswith("```json"):
            clean_result = clean_result[7:]
        elif clean_result.startswith("```"):
            clean_result = clean_result[3:]
        if clean_result.endswith("```"):
            clean_result = clean_result[:-3]
        clean_result = clean_result.strip()

        try:
            parsed = json.loads(clean_result)
            extracted_list = parsed.get("qualifications", [])
        except json.JSONDecodeError as e:
            logger.error(f"VLM JSON 解析失败: {e}\n原文: {result}")
            raise HTTPException(status_code=500, detail="VLM 返回的数据格式不正确")

        if not extracted_list:
            raise HTTPException(status_code=400, detail="未从图片中识别到任何有效的资质信息")

        mock_objs = []
        for item in extracted_list:
            qual_name = item.get("name")
            if not qual_name:
                qual_name = "未命名资质"
            
            temp_id = "temp_" + uuid.uuid4().hex
            now = datetime.utcnow()
            
            mock_obj = QualificationResponse(
                id=temp_id,
                tenant_id=tenant_id,
                name=qual_name,
                company_name=item.get("company_name"),
                level=item.get("level"),
                expiry_date=item.get("expiry_date"),
                file_url=file_url,
                created_at=now,
                updated_at=now
            )
            mock_objs.append(mock_obj)
        
        return mock_objs


company_qualification_service = CompanyQualificationService()
