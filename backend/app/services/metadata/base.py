import json
import logging
from typing import Type, TypeVar, Any
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.services.llm_service import llm_service
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

class BaseMetadataService:
    def __init__(self, db_model_cls: Any = None):
        """
        :param db_model_cls: 对应的 SQLAlchemy Model 类。如果在子类中设置，可实现自动入库。
        """
        self.db_model_cls = db_model_cls

    def extract(self, context: str, schema_cls: Type[T], system_prompt: str, document_id: str) -> T:
        """
        基于传入的上下文 context，利用大模型提取出符合 schema_cls 结构的 JSON 数据，
        并将其持久化到数据库中（如果配置了 db_model_cls）。
        """
        prompt = f"""
{system_prompt}

【任务约束】
1. 你的任务是根据下面提供的 <文本上下文> 进行信息抽取。
2. 宁缺毋滥原则：如果上下文中完全没有提及某个字段的相关信息（找不到），请将该字段值置为 null。绝不允许编造任何信息。
3. 明确豁免原则：如果上下文中**明确写明**“无需提供”、“不作要求”，请针对该字符串字段返回 `"明确无要求"`；如果写明“待定”、“另行通知”，请返回 `"待定"`。千万不要返回 null。
4. 思维链 (CoT)：如果是复杂的条款提取，可以在允许的推理字段中先写出推导过程。

<文本上下文>
{context}
</文本上下文>
"""
        logger.info(f"开始执行元数据提取: {schema_cls.__name__}, 目标文档ID: {document_id}")
        
        # 调用大模型生成结构化对象 (带有 Fallback 的双轨兜底)
        try:
            result_obj = llm_service.generate_structured_output(prompt=prompt, schema_cls=schema_cls, temperature=0.1)
        except Exception as e:
            logger.error(f"结构化输出提取彻底失败: {e}")
            raise ValueError(f"大模型提取失败: {e}")
        
        # 自动落盘到 PostgreSQL
        if self.db_model_cls and document_id:
            self._save_to_db(document_id, result_obj)
            
        return result_obj

    def _save_to_db(self, document_id: str, pydantic_obj: BaseModel):
        """将提取的数据转存为 SQLAlchemy Model 并落盘。"""
        db: Session = SessionLocal()
        try:
            record = db.query(self.db_model_cls).filter(self.db_model_cls.document_id == document_id).first()
            
            if hasattr(pydantic_obj, "model_dump"):
                data_dict = pydantic_obj.model_dump()
            else:
                data_dict = pydantic_obj.dict()
                
            # Filter data_dict to only include keys that exist as columns in the DB model (e.g. drop 'reasoning')
            valid_keys = {c.key for c in self.db_model_cls.__table__.columns}
            filtered_dict = {k: v for k, v in data_dict.items() if k in valid_keys}
                
            if record:
                for key, value in filtered_dict.items():
                    setattr(record, key, value)
            else:
                from app.db.models.project import Document
                doc = db.query(Document).filter(Document.id == document_id).first()
                if not doc:
                    raise ValueError(f"无法找到对应的文档记录以继承 tenant_id: {document_id}")
                    
                record = self.db_model_cls(document_id=document_id, tenant_id=doc.tenant_id, **filtered_dict)
                db.add(record)
                
            db.commit()
            logger.info(f"✅ 元数据 {self.db_model_cls.__name__} 已成功保存/更新至数据库, 文档ID: {document_id}")
        except Exception as e:
            db.rollback()
            logger.error(f"❌ 存入数据库失败: {str(e)}")
            raise e
        finally:
            db.close()
