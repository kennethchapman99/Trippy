from __future__ import annotations

from trippy.services.serpapi_options import activity_options_from_serpapi


def test_activity_options_keep_operator_maps_and_photos_separate() -> None:
    options = activity_options_from_serpapi(
        [
            {
                "title": "Whale Watching Ponta Delgada",
                "address": "Ponta Delgada, Sao Miguel",
                "rating": 4.8,
                "reviews": 1200,
                "types": ["Tour operator"],
                "website": "https://operator.example/tours/whales",
                "place_id": "abc123",
                "thumbnail": "https://images.example/whale.jpg",
                "photos": [{"thumbnail": "https://images.example/boat.jpg"}],
            }
        ],
        region="Sao Miguel",
        deep_link="https://www.google.com/maps/search/things+to+do+Sao+Miguel",
    )

    option = options[0]

    assert option.deep_link == "https://operator.example/tours/whales"
    assert option.validation_links["Operator website"] == option.deep_link
    assert option.validation_links["Google Maps"].startswith("https://www.google.com/maps/")
    assert option.photo_urls == [
        "https://images.example/whale.jpg",
        "https://images.example/boat.jpg",
    ]
    assert option.price_band == "open listing for price"


def test_activity_options_build_specific_maps_link_without_website() -> None:
    options = activity_options_from_serpapi(
        [
            {
                "title": "Miradouro de Santa Iria",
                "address": "San Miguel, Portugal",
                "rating": 4.8,
                "reviews": 5788,
                "types": ["Tourist attraction", "Scenic spot"],
            }
        ],
        region="Sao Miguel",
        deep_link="https://www.google.com/maps/search/things+to+do+Sao+Miguel",
    )

    option = options[0]

    assert option.deep_link.startswith("https://www.google.com/maps/search/?api=1&query=")
    assert option.validation_links == {"Google Maps": option.deep_link}
