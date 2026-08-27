import os
from loguru import logger
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.db.crud.document import document_crud

class DocumentService:
    def get_documents_list(self, db: Session, user_id: str, tenant_id: str, doc_type: str = None):
        """处理获取所有历史记录的业务逻辑，支持按 doc_type 过滤"""
        docs = document_crud.get_all_documents(db, user_id, tenant_id, doc_type=doc_type)
        docs_list = []
        for d in docs:
            pm = d.parsed_metadata or {}
            path_str = str(d.file_path or "").replace("\\", "/")
            is_bid = (
                pm.get("doc_type") == "bid" 
                or "/bids/" in path_str 
                or "temp_uploads" in path_str 
                or "bid_docs" in path_str
            )
            inferred_type = "bid" if is_bid else "tender"
            
            docs_list.append({
                "id": d.id,
                "filename": d.filename,
                "file_path": d.file_path,
                "doc_type": pm.get("doc_type") or inferred_type,
                "source_doc_id": pm.get("source_doc_id"),
                "status": d.parse_status,
                "created_at": d.created_at.isoformat() if hasattr(d, "created_at") and d.created_at else None
            })
        # 强制在 Python 层按 created_at 降序排
        docs_list.sort(key=lambda x: x["created_at"] or "", reverse=True)
        return docs_list

    def get_document_result(self, db: Session, doc_id: str, user_id: str, tenant_id: str):
        """处理获取文档详情结果的业务逻辑（降级读取 Markdown 或 Chunk，拼装超大结果字典）"""
        doc_obj = document_crud.get_document_by_id(db, doc_id, user_id, tenant_id)
        if not doc_obj:
            raise HTTPException(status_code=404, detail="文档记录未找到")
            
        md_file_path = (
            doc_obj.parsed_metadata.get("md_file_path", "")
            if doc_obj and doc_obj.parsed_metadata
            else ""
        )
        
        doc_text = ""
        # 优先读取本地完整 Markdown，否则拼接 Chunk
        if md_file_path and os.path.exists(md_file_path):
            with open(md_file_path, "r", encoding="utf-8") as f:
                doc_text = f.read()
        else:
            chunks_for_display = document_crud.get_document_chunks(db, doc_id)
            doc_text = "\n\n".join([c.content for c in chunks_for_display]) if chunks_for_display else ""

        # 加载所有维度元数据
        metadata_objs = document_crud.get_all_metadata(db, doc_id)
        metadata_dict = {}
        for key, md_obj in metadata_objs.items():
            if md_obj:
                metadata_dict[key] = {k: v for k, v in md_obj.__dict__.items() if not k.startswith('_')}

        cost_analysis = dict(doc_obj.parsed_metadata.get("cost_analysis", {})) if doc_obj.parsed_metadata else {}

        # cost_estimates 是项目 BOM 成本报价的主表；parsed_metadata 中的
        # cost_analysis 仅作为兼容旧数据和保存汇总状态的 JSON 快照。
        from app.db.models.ai_analysis import CostEstimate
        cost_rows = (
            db.query(CostEstimate)
            .filter(
                CostEstimate.document_id == doc_id,
                CostEstimate.tenant_id == tenant_id,
            )
            .order_by(CostEstimate.sort_order.asc(), CostEstimate.created_at.asc())
            .all()
        )
        if cost_rows:
            cost_analysis["items"] = [
                {
                    "id": row.id,
                    "item_code": row.item_code,
                    "name": row.item_name,
                    "spec_requirement": row.spec_requirement or "",
                    "qty": row.quantity,
                    "unit": row.unit,
                    "ref_price": row.unit_price or 0.0,
                    "subtotal": row.calculated_total or 0.0,
                    "matched_name": row.matched_name or row.item_name,
                    "matched_brand": row.matched_brand or row.brand or "",
                    "matched_model": row.matched_model or row.model or row.spec or "",
                    "matched_manufacturer": row.matched_manufacturer or row.manufacturer or "",
                    "brand": row.brand or "",
                    "model": row.model or row.spec or "",
                    "manufacturer": row.manufacturer or "",
                    "key_parameters": row.key_parameters or [],
                    "brand_requirements": row.brand_requirements or "",
                    "match_quality": row.match_quality or "",
                    "warning": row.warning or "",
                    "comparison_note": row.comparison_note or "",
                    "remark": row.remark or "",
                    "parent_item": row.parent_item,
                    "root_item": row.root_item,
                    "tree_level": row.tree_level or 1,
                    "per_set_qty": row.per_set_qty,
                    "per_set_quantity": row.per_set_quantity,
                    "section_name": row.section_name,
                }
                for row in cost_rows
            ]
            cost_analysis["total_cost"] = sum(row.calculated_total or 0.0 for row in cost_rows)
        # 自动校验与修复 cost_analysis 中的 parent_item 树形关联与 section_name 区域标签
        if cost_analysis and isinstance(cost_analysis.get("items"), list):
            eng_obj = metadata_objs.get("engineering")
            if eng_obj and hasattr(eng_obj, "main_equipment_list") and isinstance(eng_obj.main_equipment_list, list):
                eng_meta_map = {}
                for eq in eng_obj.main_equipment_list:
                    if isinstance(eq, dict) and eq.get("item_name"):
                        eng_meta_map[eq["item_name"].strip()] = {
                            "parent_item": eq.get("parent_item"),
                            "per_set_qty": eq.get("per_set_quantity") or eq.get("per_set_qty"),
                            "section_name": eq.get("section_name")
                        }
                for itm in cost_analysis["items"]:
                    if isinstance(itm, dict):
                        nm = (itm.get("name") or "").strip()
                        if nm in eng_meta_map:
                            if not itm.get("parent_item") and eng_meta_map[nm].get("parent_item"):
                                itm["parent_item"] = eng_meta_map[nm]["parent_item"]
                            if not itm.get("per_set_qty") and eng_meta_map[nm].get("per_set_qty"):
                                itm["per_set_qty"] = eng_meta_map[nm]["per_set_qty"]
                            if not itm.get("section_name") and eng_meta_map[nm].get("section_name"):
                                itm["section_name"] = eng_meta_map[nm]["section_name"]

        result = {
            "document_id": doc_id,
            "filename": doc_obj.filename,
            "extracted_text": doc_text,
            "qualifications_analysis": doc_obj.parsed_metadata.get("qualifications_analysis", {}) if doc_obj.parsed_metadata else {},
            "risks_analysis": doc_obj.parsed_metadata.get("risks_analysis", []) if doc_obj.parsed_metadata else [],
            "cost_analysis": cost_analysis,
            "metadata": metadata_dict
        }
        
        return result

    def delete_document(self, db: Session, doc_id: str, user_id: str, tenant_id: str):
        """处理文档删除的业务逻辑（含数据库记录级联删除与本地文件物理清理）"""
        doc_obj = document_crud.get_document_by_id(db, doc_id, user_id, tenant_id)
        if not doc_obj:
            raise HTTPException(status_code=404, detail="文档记录未找到")
        
        # 记录待删除的物理路径
        file_path = doc_obj.file_path
        md_file_path = (doc_obj.parsed_metadata or {}).get("md_file_path", "")

        # 数据库级联删除
        try:
            document_crud.delete_document(db, doc_obj)
        except Exception as e:
            db.rollback()
            logger.error(f"级联删除文档 {doc_id} 的数据库记录失败: {e}")
            raise HTTPException(status_code=500, detail="删除数据库记录失败")

        # 尝试静默删除本地物理文件
        for path_to_delete in [file_path, md_file_path]:
            if path_to_delete and os.path.exists(path_to_delete):
                try:
                    os.remove(path_to_delete)
                    logger.info(f"成功清理本地残留文件: {path_to_delete}")
                except Exception as e:
                    logger.warning(f"未能彻底清理物理文件 {path_to_delete}: {e}")

    def get_document_file_for_download(self, db: Session, doc_id: str, user_id: str, tenant_id: str) -> tuple[str, str]:
        """获取指定文档的原文件物理路径与文件名（含多租户权限校验与多级候选路径探测）"""
        from pathlib import Path
        doc_obj = document_crud.get_document_by_id(db, doc_id, user_id, tenant_id)
        if not doc_obj:
            raise HTTPException(status_code=404, detail="文档记录未找到或无权访问")

        raw_path = str(doc_obj.file_path or "").strip()
        candidate_paths = []
        if raw_path:
            candidate_paths.append(raw_path)
            if not os.path.isabs(raw_path):
                # 尝试相对于 backend 根目录解析
                backend_base = Path(__file__).resolve().parent.parent.parent
                candidate_paths.append(str(backend_base / raw_path))

        target_path = None
        for path in candidate_paths:
            if os.path.exists(path) and os.path.isfile(path):
                target_path = path
                break

        # 若直接路径未命中，尝试在常见上传存储目录中查找
        if not target_path:
            backend_base = Path(__file__).resolve().parent.parent.parent
            search_dirs = [
                backend_base / "uploads" / "tenders",
                backend_base / "uploads" / "bids",
                backend_base / "uploads",
                backend_base / "storage" / "temp_uploads",
            ]
            for sdir in search_dirs:
                if sdir.exists() and sdir.is_dir():
                    for fname in os.listdir(sdir):
                        if (doc_id in fname) or (doc_obj.filename and fname.endswith(doc_obj.filename)):
                            cand = str(sdir / fname)
                            if os.path.isfile(cand):
                                target_path = cand
                                break
                    if target_path:
                        break

        if not target_path or not os.path.exists(target_path):
            logger.warning(f"下载原文件失败，物理文件不存在: doc_id={doc_id}, file_path={raw_path}")
            raise HTTPException(status_code=404, detail="未在服务器上找到该文档的原文件")

        return target_path, doc_obj.filename

document_service = DocumentService()

