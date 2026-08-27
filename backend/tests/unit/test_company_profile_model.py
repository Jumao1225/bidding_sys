"""企业档案模型与空档案初始化逻辑测试。"""

from app.api.endpoints.company_profile import get_company_profile
from app.db.models import Base, CompanyProfileModel


class _FakeQuery:
    """提供企业档案查询所需的最小测试替身。"""

    def __init__(self, profile: CompanyProfileModel | None):
        self.profile = profile

    def filter(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def order_by(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def first(self) -> CompanyProfileModel | None:
        return self.profile


class _FakeSession:
    """记录空档案创建过程，避免单元测试连接真实数据库。"""

    def __init__(self, profile: CompanyProfileModel | None = None):
        self.profile = profile
        self.added_profile: CompanyProfileModel | None = None
        self.commit_count = 0
        self.refresh_count = 0

    def query(self, model: type[CompanyProfileModel]) -> _FakeQuery:
        assert model is CompanyProfileModel
        return _FakeQuery(self.profile)

    def add(self, profile: CompanyProfileModel) -> None:
        self.added_profile = profile
        self.profile = profile

    def commit(self) -> None:
        self.commit_count += 1

    def refresh(self, profile: CompanyProfileModel) -> None:
        self.refresh_count += 1
        if profile.id is None:
            profile.id = "test-company-profile"


def test_company_profile_should_use_shared_metadata() -> None:
    """企业档案表必须注册到 Alembic 使用的共享元数据中。"""
    assert CompanyProfileModel.metadata is Base.metadata
    assert "company_profiles" in Base.metadata.tables


def test_get_company_profile_existing_record_should_return_record() -> None:
    """已有企业档案时，接口应直接返回现有记录。"""
    profile = CompanyProfileModel(company_name="测试公司")
    db = _FakeSession(profile=profile)

    result = get_company_profile(db=db)

    assert result is profile
    assert db.added_profile is None
    assert db.commit_count == 0


def test_get_company_profile_without_record_should_create_empty_profile() -> None:
    """没有企业档案时，应创建允许为空的初始记录。"""
    db = _FakeSession()

    result = get_company_profile(db=db)

    assert result is db.added_profile
    assert result.company_name is None
    assert db.commit_count == 1
    assert db.refresh_count == 1
