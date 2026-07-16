import redis
import json
import os
from datetime import datetime, date
from loguru import logger
from app.core.celery_app import celery_app
from app.core.config import settings
from app.graph.builder import bidding_graph
from app.core.context import current_task_id

# 初始化 redis 客户端用于 pub/sub
redis_client = redis.from_url(settings.REDIS_URL)

def publish_progress(task_id: str, status: str, progress: int, result: dict = None):
    """
    推送进度信息到 Redis Pub/Sub 供 SSE 读取
    """
    message = {
        "status": status,
        "progress": progress,
    }
    if result is not None:
        message["result"] = result
        
    def json_serial(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    # ensure_ascii=False：保证中文直接以 UTF-8 写入，禁止输出 \uXXXX 转义
    redis_client.publish(f"channel:{task_id}", json.dumps(message, ensure_ascii=False, default=json_serial))

def emit_agent_log(log_type: str, content: str):
    """
    流式推送 Agent 思考/动作日志到前端终端
    log_type: 'info' | 'tool_call' | 'success' | 'error'
    """
    task_id = current_task_id.get()
    if task_id:
        message = {
            "status": "Agent 处理中...",
            "progress": 50,  # Maintain a static progress or let frontend ignore it
            "agent_log": {
                "type": log_type,
                "content": content
            }
        }
        
        def json_serial(obj):
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")

        # ensure_ascii=False：保证 agent_log 里的中文字符不被转义为 \uXXXX
        redis_client.publish(f"channel:{task_id}", json.dumps(message, ensure_ascii=False, default=json_serial))

@celery_app.task(bind=True, name="analyze_bidding_doc")
def analyze_bidding_doc(self, task_id: str, file_path: str, filename: str, company_quals: str):
    """
    后台处理招标文件解析和 AI 分析
    """
    logger.info(f"Task {task_id} started for file {filename}")
    publish_progress(task_id, "开始处理", 10)
    
    from app.db.session import SessionLocal
    from app.db.models.project import Project, Document, DocChunk
    
    db = SessionLocal()
    doc_id = None
    try:
        # 1. 创建默认 Project (如果需要) 并插入 Document 记录供 Extractor 使用
        publish_progress(task_id, "初始化任务与数据库...", 15)
        
        project = db.query(Project).filter(Project.name == "Frontend Uploads").first()
        if not project:
            project = Project(tenant_id="default-tenant", name="Frontend Uploads", status="created")
            db.add(project)
            db.commit()
            db.refresh(project)
            
        import hashlib
        with open(file_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
            
        # 查找是否已经有同名且内容哈希一致的文件
        docs_with_same_name = db.query(Document).filter(
            Document.project_id == project.id,
            Document.filename == filename
        ).all()
        
        exact_match_doc = None
        for d in docs_with_same_name:
            if d.parsed_metadata and d.parsed_metadata.get("file_hash") == file_hash:
                exact_match_doc = d
                break

        if exact_match_doc and exact_match_doc.parse_status == "completed":
            doc_id = exact_match_doc.id
            publish_progress(task_id, "检测到完全相同的文件缓存，跳过解析...", 20)
        else:
            if exact_match_doc:
                # 只有当哈希完全一样但状态是 pending/failed 时，才删掉这条半成品记录重试
                db.delete(exact_match_doc) 
                db.commit()

            # 只要哈希不同，哪怕文件名一模一样，也会当做一份全新的记录建档（不删除旧的）

            doc = Document(
                tenant_id="default-tenant",
                project_id=project.id,
                filename=filename,
                file_path=file_path,
                parse_status="pending",
                parsed_metadata={"file_hash": file_hash}
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            doc_id = doc.id
            publish_progress(task_id, "正在提取文本与生成向量 (MinerU + BGE-M3)...", 20)
        
        # 2. 调用 LangGraph
        initial_state = {
            "task_id": task_id,
            "document_id": doc_id,
            "doc_text": "",
            "company_quals": company_quals,
            "status": "RUNNING",
            "error": ""
        }
        
        # 注入 ContextVar
        token = current_task_id.set(task_id)
        
        try:
            # graph.invoke 会返回最终状态
            final_state = bidding_graph.invoke(initial_state)
        finally:
            current_task_id.reset(token)
        
        # -------------------------------------------------------------------------
        # 从 parsed_metadata 读取 output.md 路径，优先使用原始无切割全文供前端展示
        # 避免将带 CHUNK_OVERLAP 重叠区的 Chunk 内容拼接后暴露给用户
        # -------------------------------------------------------------------------
        # 注意：parser_worker 使用独立的 db session 提交了 parsed_metadata 的更新，
        # 而当前 session 的 Identity Map 可能缓存了旧对象。
        # 必须先 expire_all()，强制 SQLAlchemy 在下次访问时重新从数据库读取最新数据。
        db.expire_all()
        doc_obj = db.query(Document).filter(Document.id == doc_id).first()
        md_file_path = (
            doc_obj.parsed_metadata.get("md_file_path", "")
            if doc_obj and doc_obj.parsed_metadata
            else ""
        )
        
        if md_file_path and os.path.exists(md_file_path):
            with open(md_file_path, "r", encoding="utf-8") as f:
                doc_text = f.read()
            logger.info(f"成功从 output.md 读取原始 Markdown 全文用于前端展示 ({len(doc_text)} 字)")
        else:
            # 降级回退：从数据库 Chunk 拼接（注意：此方案包含 CHUNK_OVERLAP 重叠文本）
            logger.warning("未找到 output.md 原始文件，降级使用 Chunk 内容拼接模式（前端可能出现重叠文本）")
            chunks_for_display = db.query(DocChunk).filter(
                DocChunk.document_id == doc_id
            ).order_by(DocChunk.chunk_index).all()
            doc_text = "\n\n".join([c.content for c in chunks_for_display]) if chunks_for_display else ""

        # 从数据库加载大模型落盘的 5 大元数据供前端面板渲染
        from app.db.models.metadata import (
            QualificationMetadata, FinancialMetadata, TimelineMetadata, 
            EngineeringMetadata, EvaluationMetadata
        )
        metadata_dict = {}
        qual_md = db.query(QualificationMetadata).filter(QualificationMetadata.document_id == doc_id).first()
        fin_md = db.query(FinancialMetadata).filter(FinancialMetadata.document_id == doc_id).first()
        time_md = db.query(TimelineMetadata).filter(TimelineMetadata.document_id == doc_id).first()
        eng_md = db.query(EngineeringMetadata).filter(EngineeringMetadata.document_id == doc_id).first()
        eval_md = db.query(EvaluationMetadata).filter(EvaluationMetadata.document_id == doc_id).first()
        
        if qual_md:
            metadata_dict["qualification"] = {k: v for k, v in qual_md.__dict__.items() if not k.startswith('_')}
        if fin_md:
            metadata_dict["financial"] = {k: v for k, v in fin_md.__dict__.items() if not k.startswith('_')}
        if time_md:
            metadata_dict["timeline"] = {k: v for k, v in time_md.__dict__.items() if not k.startswith('_')}
        if eng_md:
            metadata_dict["engineering"] = {k: v for k, v in eng_md.__dict__.items() if not k.startswith('_')}
        if eval_md:
            metadata_dict["evaluation"] = {k: v for k, v in eval_md.__dict__.items() if not k.startswith('_')}

        # 将 strategy agent 产出的策略分析数据统一写回数据库持久化，与其他数据共存
        if doc_obj:
            current_meta = dict(doc_obj.parsed_metadata) if doc_obj.parsed_metadata else {}
            current_meta["qualifications_analysis"] = final_state.get("qualifications_analysis", {})
            current_meta["risks_analysis"] = final_state.get("risks_analysis", [])
            doc_obj.parsed_metadata = current_meta
            db.commit()

        # 提取结果用于前端展示
        # document_id 需随 result 一并下发，供 ChatPanel 聊天接口使用
        result = {
            "document_id": doc_id,
            "extracted_text": doc_text,
            "qualifications_analysis": final_state.get("qualifications_analysis", {}),
            "risks_analysis": final_state.get("risks_analysis", []),
            "cost_analysis": final_state.get("cost_analysis", {}),
            "metadata": metadata_dict  # 注入面板所需的核心数据
        }
        
        if final_state.get("status") == "extractor_failed" or final_state.get("error"):
            raise Exception(final_state.get("error", "智能体执行失败"))
            
        publish_progress(task_id, "完成", 100, result=result)
        logger.info(f"Task {task_id} completed.")
        return final_state
        
    except Exception as e:
        logger.exception(f"Task {task_id} failed: {e}")
        publish_progress(task_id, f"错误: {str(e)}", 100, result={"error": str(e)})
        raise e
    finally:
        db.close()
        # 清理临时文件 - 暂时禁用，前端需要读取原文件预览
        # if os.path.exists(file_path):
        #     os.remove(file_path)
        pass

@celery_app.task(name="async_write_audit_log")
def async_write_audit_log(
    task_id: str,
    node_name: str,
    action_type: str,
    inputs: dict = None,
    outputs: dict = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    execution_time_ms: int = None,
    status: str = "success",
    error_message: str = None
):
    """
    异步将审计日志写入数据库
    """
    from app.db.session import SessionLocal
    from app.db.models.audit import AgentAuditLog

    db = SessionLocal()
    try:
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        log_entry = AgentAuditLog(
            tenant_id="default-tenant",
            task_id=task_id,
            node_name=node_name,
            action_type=action_type,
            inputs=inputs,
            outputs=outputs,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            execution_time_ms=execution_time_ms,
            status=status,
            error_message=error_message
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")
    finally:
        db.close()
