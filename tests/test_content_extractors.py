from __future__ import annotations

import pytest

from journeyplus.content.cleaner import lightly_clean
from journeyplus.content.extractors import ContentExtractionError
from journeyplus.contracts import RawDocument


def _raw(
    *,
    source_id: str,
    body: str,
    strategy: str,
    title: str = "Feed title",
    url: str = "https://example.com/article",
) -> RawDocument:
    return RawDocument(
        source_id=source_id,
        external_id="fixture",
        canonical_url=url,
        body=body,
        content_type="text/html",
        metadata={"content_strategy": strategy, "title": title},
    )


def test_ffb_article_uses_entry_content_and_keeps_meaningful_links() -> None:
    cleaned = lightly_clean(
        _raw(
            source_id="ffb_elite_status_feed",
            strategy="fetch_article",
            body="""
                <html><body>
                  <nav>Site menu</nav>
                  <h1 class="entry-title">Kenya Airways Match</h1>
                  <div class="entry-content">
                    <p>Match details and <a href="https://airline.test/apply">apply here</a>.</p>
                    <figure><img src="https://cdn.test/offer.jpg" alt="offer chart">
                      <figcaption>Status tiers</figcaption></figure>
                    <img src="https://cdn.test/deadline.png" alt="Offer deadline table">
                    <img src="https://cdn.test/decorative.png" alt>
                    <h2>Eligible tiers</h2>
                    <p><img src="https://cdn.test/tier-1.png" alt="">
                       <img src="https://cdn.test/tier-2.png" alt=""></p>
                    <div class="sfsi_Sicons">Share this offer</div>
                  </div>
                  <section class="comments">Reader comments</section>
                </body></html>
            """,
        )
    ).normalized_body

    assert cleaned.startswith("# Kenya Airways Match")
    assert "[apply here](https://airline.test/apply)" in cleaned
    assert "Status tiers" in cleaned
    assert "[图片：Offer deadline table]" in cleaned
    assert "[图片：Eligible tiers（图片文字未提取）]" in cleaned
    assert "cdn.test" not in cleaned
    assert "Site menu" not in cleaned
    assert "Share this offer" not in cleaned
    assert "Reader comments" not in cleaned


def test_awardwallet_article_removes_template_modules_but_keeps_editorial_text() -> None:
    cleaned = lightly_clean(
        _raw(
            source_id="awardwallet_elite_status_feed",
            strategy="fetch_article",
            body="""
                <html><body>
                  <header>Site header</header>
                  <h1 class="page-learn__hero-title">Globalist Guide</h1>
                  <article>
                    <div id="preDisclosure">Advertiser disclosure</div>
                    <div id="ftoc">Table of contents</div>
                    <p>Globalist members receive breakfast.</p>
                    <p>Read the <a href="/terms">official terms</a>.</p>
                    <div class="compare-cards-wrap">Card comparison widget</div>
                    <p class="remark">Affiliate-card template note</p>
                  </article>
                  <aside>Popular posts</aside>
                </body></html>
            """,
        )
    ).normalized_body

    assert cleaned.startswith("# Globalist Guide")
    assert "Globalist members receive breakfast" in cleaned
    assert "[official terms](https://example.com/terms)" in cleaned
    assert "Advertiser disclosure" not in cleaned
    assert "Table of contents" not in cleaned
    assert "Card comparison widget" not in cleaned
    assert "Affiliate-card template note" not in cleaned
    assert "Site header" not in cleaned
    assert "Popular posts" not in cleaned


def test_buy_points_article_cleanup_keeps_offer_tables_and_removes_modules() -> None:
    cleaned = lightly_clean(
        _raw(
            source_id="awardwallet_buy_points_page",
            strategy="fetch_article",
            title="Buy Points Promotions",
            url=(
                "https://awardwallet.com/news/"
                "current-promotions-buy-points-miles/"
            ),
            body="""
                <html><body><header>Navigation</header><article>
                  <div id="preDisclosure">Advertiser disclosure</div>
                  <div id="ftoc">Table of contents</div>
                  <h2 id="Buy_Miles_Promotions_From_Airlines">Airlines</h2>
                  <div class="purchase-times purchase-times--date">
                    <div class="pt-row">Southwest 50% discount</div>
                  </div>
                  <div class="compare-cards-wrap">Credit card widget</div>
                </article><footer>Footer</footer></body></html>
            """,
        )
    ).normalized_body

    assert cleaned.startswith("# Buy Points Promotions")
    assert "Southwest 50% discount" in cleaned
    assert "Advertiser disclosure" not in cleaned
    assert "Table of contents" not in cleaned
    assert "Credit card widget" not in cleaned
    assert "Navigation" not in cleaned
    assert "Footer" not in cleaned


@pytest.mark.parametrize(
    ("source_id", "tail"),
    [
        (
            "frequentmiler_elite_status_feed",
            '<div class="sharethis-inline-share-buttons">Share</div>'
            '<p>The post Offer first appeared on Frequent Miler.</p>',
        ),
        (
            "verylvke_feed",
            "<p>The post 活动 first appeared on 飞常旅客 VERYLVKE.</p>",
        ),
    ],
)
def test_feed_body_removes_wordpress_distribution_tail(
    source_id: str, tail: str
) -> None:
    cleaned = lightly_clean(
        _raw(
            source_id=source_id,
            strategy="feed_body_only",
            title="Status offer",
            body=(
                '<p>Offer body with <a href="https://program.test/register">registration</a>.</p>'
                + tail
            ),
        )
    ).normalized_body

    assert cleaned.startswith("# Status offer")
    assert "[registration](https://program.test/register)" in cleaned
    assert "Share" not in cleaned
    assert "first appeared" not in cleaned


def test_frequentmiler_removes_hidden_card_widget_noise_only() -> None:
    cleaned = lightly_clean(
        _raw(
            source_id="frequentmiler_elite_status_feed",
            strategy="feed_body_only",
            title="Card status guide",
            url="https://frequentmiler.com/card-guide/",
            body="""
                <h3><img src="decorative.jpg" alt=""></h3>
                <div class="BObox">
                  <div class="BOhd"><a href="/card/">Status Card</a></div>
                  <div class="BOfyv">Estimated value tooltip</div>
                  <div class="BObon">100 XP <span class="BOban">Non-Affiliate</span></div>
                  <div class="BOmo">Earn status after qualifying spend.</div>
                  <div class="BOline"><small>Issuer disclosure.</small></div>
                  <div class="BOtbl">Big spend bonus: 100 XP</div>
                </div>
            """,
        )
    ).normalized_body

    assert "[Status Card](https://frequentmiler.com/card/)" in cleaned
    assert "Earn status after qualifying spend" in cleaned
    assert "Big spend bonus: 100 XP" in cleaned
    assert "Estimated value tooltip" not in cleaned
    assert "Non-Affiliate" not in cleaned
    assert "Issuer disclosure" not in cleaned
    assert "###" not in cleaned


def test_loyaltylobby_removes_only_self_referential_source_link() -> None:
    article_url = "https://loyaltylobby.com/2026/08/offer/"
    cleaned = lightly_clean(
        _raw(
            source_id="loyaltylobby_feed",
            strategy="feed_body_only",
            title="Offer",
            url=article_url,
            body=(
                '<p>See <a href="https://program.test/terms">official terms</a>.</p>'
                f'<p><a href="{article_url}?omhide=true">Source</a></p>'
            ),
        )
    ).normalized_body

    assert "[official terms](https://program.test/terms)" in cleaned
    assert "Source" not in cleaned


def test_fetch_article_fails_loudly_when_expected_container_disappears() -> None:
    with pytest.raises(ContentExtractionError, match="Expected article selector"):
        lightly_clean(
            _raw(
                source_id="ffb_elite_status_feed",
                strategy="fetch_article",
                body="<html><body><main>Changed layout</main></body></html>",
            )
        )
