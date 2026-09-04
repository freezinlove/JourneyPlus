"""Local single-user personalized status-match product."""


def create_product_app(*args, **kwargs):
    """Load the web application lazily to keep product contracts import-safe."""
    from journeyplus.product.api import create_product_app as factory

    return factory(*args, **kwargs)


__all__ = ["create_product_app"]
