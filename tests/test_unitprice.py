from decimal import Decimal

from collector.attributes import attributes_of
from collector.unitprice import UnitPrice, contents, unit_price

D = Decimal


def price_of(name, price, **fields):
    return unit_price(D(price), attributes_of(name, **fields).size)


def test_per_litre():
    assert price_of("חלב בקרטון 3% שומן 1 ל", "7.35") == UnitPrice(D("7.35"), "l")
    assert price_of('שמן זית 750 מ"ל', "30.00") == UnitPrice(D("40.00"), "l")


def test_multipack_is_priced_by_the_total():
    assert price_of("מים מינרליים 6*1.5 ליטר", "18.00") == UnitPrice(D("2.00"), "l")


def test_per_kilo():
    assert price_of("קוטג' תנובה 5% 250 גרם", "5.90") == UnitPrice(D("23.60"), "kg")
    assert price_of('אורז בסמטי 1 ק"ג', "12.90") == UnitPrice(D("12.90"), "kg")


def test_weighted_item_stays_per_kilo():
    assert price_of("עגבניה שרי", "11.90", is_weighted=True) == UnitPrice(D("11.90"), "kg")


def test_per_unit():
    assert price_of("שקיות אשפה 30 יח'", "12.00") == UnitPrice(D("0.40"), "unit")


def test_rounds_to_agorot_half_up():
    assert price_of("גבינה 300 גרם", "7.00") == UnitPrice(D("23.33"), "kg")
    assert price_of("גבינה 400 גרם", "5.01") == UnitPrice(D("12.53"), "kg")  # 12.525


def test_no_size_no_unit_price():
    assert price_of("לחם אחיד פרוס", "6.50") is None
    assert unit_price(D("5"), None) is None


def test_what_the_website_divides_by():
    assert contents(attributes_of("מיץ 1.5 ליטר").size) == (D("1.5"), "l")
    assert contents(attributes_of("קמח 500 גרם").size) == (D("0.5"), "kg")
    assert contents(attributes_of("ביצים 12 יחידות").size) == (D("12"), "unit")
    assert str(contents(attributes_of('אורז 10 ק"ג').size)[0]) == "10"
