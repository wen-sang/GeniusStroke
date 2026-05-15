from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

class AssetBase(BaseModel):
    asset_name: str = Field(..., description="资产名称")
    asset_type: str = Field(default="INDEX", description="资产类型(INDEX/ETF/STOCK/FUND)")
    exchange: Optional[str] = Field(None, description="交易所(SH/SZ/HK)")
    listing_date: Optional[str] = Field(None, description="上市日期 YYYY-MM-DD")
    market_category: str = Field(default="EXCHANGE", description="市场类别(EXCHANGE/OTC)")

class AssetCreate(AssetBase):
    asset_code: str = Field(..., description="资产代码")
    source_id: str = Field(..., description="资产路由数据源标识(lixinren/akshare)")
    source_code: Optional[str] = Field(None, description="数据源侧标的代码")

class AssetUpdate(AssetBase):
    source_id: str = Field(..., description="资产路由数据源标识(lixinren/akshare)")
    source_code: Optional[str] = Field(None, description="数据源侧标的代码")

class AssetResponse(AssetCreate):
    is_active: int = Field(default=1, description="是否在市")
    model_config = ConfigDict(from_attributes=True)
