import pytest

from app.digest import group, url_key


def test_query_article_ids_stay_distinct():
    urls = ["https://example.org/?p=101", "https://example.org/?p=102"]
    assert url_key(urls[0]) != url_key(urls[1])
    items = [{"url": url, "source": "hackernews", "rank": rank, "points": 1}
             for rank, url in enumerate(urls, 1)]
    assert len(group(items)) == 2


@pytest.mark.parametrize("tracking", ["utm_source", "utm_campaign", "UTM_MEDIUM", "ref", "ref_src",
                                     "fbclid", "gclid", "mc_cid", "mc_eid", "si", "source", "msclkid"])
def test_only_tracking_parameters_are_removed(tracking):
    assert url_key(f"https://www.example.org/article/?p=101&{tracking}=ad#section") == "example.org/article?p=101"


def test_query_order_and_blank_and_repeated_values():
    assert url_key("https://example.org/?b=2&a=1") == url_key("https://example.org/?a=1&b=2")
    assert url_key("https://example.org/?tag=a&tag=b&empty=") == "example.org?empty=&tag=a&tag=b"
    assert url_key("https://example.org/?tag=a&tag=b") != url_key("https://example.org/?tag=b&tag=a")
    assert url_key("https://example.org/?utm_source=ad") == "example.org"


@pytest.mark.parametrize("host,path,query", [("youtube.com", "/watch", "v=abc&si=tracking"),
                                           ("news.hada.io", "/topic", "id=101&ref=x"),
                                           ("news.ycombinator.com", "/item", "id=102&ref=x")])
def test_special_cases_keep_original_query(host, path, query):
    assert url_key(f"https://{host}{path}?{query}") == f"{host}{path}?{query}"
