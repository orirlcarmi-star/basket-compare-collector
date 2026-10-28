from datetime import datetime
from decimal import Decimal

from collector.model import Audience
from collector.parse import (
    classify_audience,
    parse_price_file,
    parse_promo_file,
    parse_stores_file,
)

# Shape of a real Shufersal PriceFull file (trimmed).
PRICE_FILE = """<Root>
  <ChainID>7290027600007</ChainID><SubChainID>001</SubChainID><StoreID>002</StoreID>
  <Items>
    <Item>
      <PriceUpdateTime>2025-12-12T01:00:00</PriceUpdateTime>
      <ItemCode>7290004131074</ItemCode>
      <ItemName>חלב בקרטון 3% שומן 1 ל</ItemName>
      <ManufactureName>תנובה בע"מ</ManufactureName>
      <UnitQty>ליטר</UnitQty><Quantity>1.00</Quantity>
      <bIsWeighted>0</bIsWeighted>
      <ItemPrice>7.35</ItemPrice><UnitOfMeasurePrice>7.35</UnitOfMeasurePrice>
    </Item>
    <Item>
      <PriceUpdateTime>2026-03-10T06:29:23.000</PriceUpdateTime>
      <ItemCode>7290000042015</ItemCode>
      <ItemName>חלב 3% מהדרין שקית 1 ל</ItemName>
      <ManufactureName>---</ManufactureName>
      <ItemPrice>6.41</ItemPrice>
    </Item>
    <Item><ItemCode>123</ItemCode><ItemName>בלי מחיר</ItemName><ItemPrice></ItemPrice></Item>
  </Items>
</Root>"""


def test_price_file_header_and_items():
    parsed = parse_price_file(PRICE_FILE)
    assert parsed.header.chain_id == "7290027600007"
    assert parsed.header.store_id == "002"
    assert [i.item_code for i in parsed.items] == ["7290004131074", "7290000042015"]


def test_price_item_fields_are_exact_decimals():
    milk = parse_price_file(PRICE_FILE).items[0]
    assert milk.price == Decimal("7.35")
    assert milk.quantity == Decimal("1.00")
    assert milk.unit == "ליטר"
    assert milk.is_weighted is False
    assert milk.updated_at == datetime(2025, 12, 12, 1, 0)


def test_placeholder_manufacturer_becomes_empty_and_priceless_items_are_skipped():
    items = parse_price_file(PRICE_FILE).items
    assert items[1].manufacturer == ""
    assert "123" not in {i.item_code for i in items}


def test_tags_are_matched_case_insensitively():
    upper = "<ROOT><CHAINID>1</CHAINID><ITEMS><ITEM><ITEMCODE>9</ITEMCODE>"
    upper += "<ITEMPRICE>2.50</ITEMPRICE></ITEM></ITEMS></ROOT>"
    parsed = parse_price_file(upper)
    assert parsed.header.chain_id == "1"
    assert parsed.items[0].price == Decimal("2.50")


PROMO_FILE = """<Root><ChainID>7290027600007</ChainID><StoreID>413</StoreID><Promotions>
  <Promotion>
    <PromotionID>1</PromotionID>
    <PromotionDescription>10 אורז בסמטי גונאם 1 ק"ג-ישיר</PromotionDescription>
    <PromotionStartDateTime>2026-10-01T00:00:00.000</PromotionStartDateTime>
    <PromotionEndDateTime>2026-11-01T00:00:00.000</PromotionEndDateTime>
    <ClubID>0 - כלל הלקוחות</ClubID><AdditionalIsCoupon>0</AdditionalIsCoupon>
    <Groups><Group><MinPurchaseAmount></MinPurchaseAmount><PromotionItems>
      <PromotionItem><ItemCode>8906163078370</ItemCode><RewardType>3</RewardType>
        <MinQty>1.00</MinQty><DiscountedPrice>10.00</DiscountedPrice></PromotionItem>
    </PromotionItems></Group></Groups>
  </Promotion>
  <Promotion>
    <PromotionID>2</PromotionID>
    <PromotionDescription>SBOX מבצע כ.אשראי</PromotionDescription>
    <ClubID>0 - כלל הלקוחות</ClubID><AdditionalIsCoupon>0</AdditionalIsCoupon>
    <Groups><Group><MinPurchaseAmount>200</MinPurchaseAmount><PromotionItems>
      <PromotionItem><ItemCode>1</ItemCode><RewardType>12</RewardType></PromotionItem>
    </PromotionItems></Group></Groups>
  </Promotion>
</Promotions></Root>"""


def test_promo_file_fixed_price_deal():
    deal = parse_promo_file(PROMO_FILE).promotions[0]
    assert deal.audience is Audience.EVERYONE
    assert deal.is_coupon is False
    assert deal.items[0].discounted_price == Decimal("10.00")
    assert deal.min_purchase_amount is None


def test_credit_card_deal_marked_everyone_is_still_detected():
    deal = parse_promo_file(PROMO_FILE).promotions[1]
    assert deal.audience is Audience.CREDIT_CARD
    assert deal.min_purchase_amount == Decimal("200")


def test_classify_audience_rules():
    assert classify_audience("0 - כלל הלקוחות", "2ב20 פריכיות", ["1"]) is Audience.EVERYONE
    assert classify_audience("3 - מועדון לקוחות", "מתנה", ["0"]) is Audience.CLUB
    assert classify_audience("2 - מועדון אשראי", "", ["3"]) is Audience.CREDIT_CARD


STORES_FILE = """<Root><ChainID>7290058140886</ChainID><SubChains><SubChain>
  <SubChainID>001</SubChainID><Stores>
    <Store><StoreID>001</StoreID><StoreName>תלפיות</StoreName><Address>יד חרוצים</Address>
      <City>3000</City></Store>
    <Store><StoreID>039</StoreID><StoreName>מרלוג אינטרנט</StoreName><City>0</City></Store>
  </Stores></SubChain></SubChains></Root>"""


def test_stores_file_marks_online_store():
    stores = parse_stores_file(STORES_FILE)
    assert [(s.store_id, s.is_online) for s in stores] == [("001", False), ("039", True)]
    assert stores[0].chain_id == "7290058140886"
    assert stores[0].sub_chain_id == "001"
