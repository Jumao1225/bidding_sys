"""
单元测试：物理存储目录隔离与 doc_type 元数据过滤测试 (test_document_path_isolation.py)
"""

import pytest
import os
from app.db.session import SessionLocal
from app.db.crud.document import document_crud
from app.db.models.project import Project, Document
from app.services.document_service import document_service

def test_document_crud_doc_type_filtering():
    """测试 CRUDDocument.get_all_documents 按 doc_type (tender vs bid) 进行准确过滤"""
    db_session = SessionLocal()
    tender_doc = None
    bid_doc = None
    project = None
    try:
        # 1. 创建测试 Project
        project = Project(tenant_id="test-tenant", name="Isolation Test Project", status="created")
        db_session.add(project)
        db_session.flush()

        # 2. 创建一个招标文件 (tender)
        tender_doc = Document(
            tenant_id="test-tenant",
            user_id="test-user",
            project_id=project.id,
            filename="test_tender_doc.docx",
            file_path="uploads/tenders/test_tender_doc.docx",
            parse_status="completed",
            parsed_metadata={"doc_type": "tender", "file_hash": "hash_tender_123"}
        )
        db_session.add(tender_doc)

        # 3. 创建一个投标文件 (bid)
        bid_doc = Document(
            tenant_id="test-tenant",
            user_id="test-user",
            project_id=project.id,
            filename="test_bid_doc.pdf",
            file_path="uploads/bids/test_bid_doc.pdf",
            parse_status="completed",
            parsed_metadata={"doc_type": "bid", "file_hash": "hash_bid_456"}
        )
        db_session.add(bid_doc)
        db_session.commit()

        # 4. 测试过滤 tender
        tenders = document_crud.get_all_documents(db_session, user_id="test-user", tenant_id="test-tenant", doc_type="tender")
        tender_ids = [d.id for d in tenders]
        assert tender_doc.id in tender_ids
        assert bid_doc.id not in tender_ids

        # 5. 测试过滤 bid
        bids = document_crud.get_all_documents(db_session, user_id="test-user", tenant_id="test-tenant", doc_type="bid")
        bid_ids = [d.id for d in bids]
        assert bid_doc.id in bid_ids
        assert tender_doc.id not in bid_ids

        # 6. 测试 DocumentService.get_documents_list
        list_tenders = document_service.get_documents_list(db_session, user_id="test-user", tenant_id="test-tenant", doc_type="tender")
        list_tender_ids = [item["id"] for item in list_tenders]
        assert tender_doc.id in list_tender_ids
        assert bid_doc.id not in list_tender_ids

    finally:
        if tender_doc:
            db_session.delete(tender_doc)
        if bid_doc:
            db_session.delete(bid_doc)
        if project:
            db_session.delete(project)
        db_session.commit()
        db_session.close()
