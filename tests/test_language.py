"""Tests for the conservative section-language classifier (--english-only)."""

from __future__ import annotations

from pagespeak.services._language import section_is_non_english


def test_english_prose_kept() -> None:
    assert not section_is_non_english(
        "The metabolic reactions that occur in the body perform many functions. "
        "One of the most important is to enable cells to do work and to grow."
    )


def test_chinese_dropped() -> None:
    assert section_is_non_english(
        "使用微功率短距离无线电发射设备应当符合国家无线电管理有关规定。"
        "具体条款见产品说明书，本产品符合相关标准与要求。"
    )


def test_russian_dropped() -> None:
    assert section_is_non_english(
        "Благодарность за покупку микрофона. Краткое описание элементов "
        "управления и технические характеристики устройства приведены ниже."
    )


def test_french_dropped() -> None:
    assert section_is_non_english(
        "Remarque importante : informations sur la gestion de l'alimentation "
        "pour les clients résidant dans les pays européens. Veuillez consulter "
        "le manuel avant toute utilisation de cet appareil électronique."
    )


def test_german_dropped() -> None:
    assert section_is_non_english(
        "Wichtiger Hinweis: Garantie-Information für Kunden in der EWR. Bitte "
        "lesen Sie die Bedienungsanleitung sorgfältig durch und bewahren Sie "
        "diese zum späteren Nachschlagen sicher auf."
    )


def test_short_section_kept() -> None:
    assert not section_is_non_english("Power input jack")
    assert not section_is_non_english("致谢")  # short non-English → too short to judge


def test_english_with_greek_math_kept() -> None:
    assert not section_is_non_english(
        "The free energy change is approximately 7 kcal per mole, where ΔE = +7. "
        "The reaction requires six oxygen molecules and produces water as a product."
    )


def test_technical_english_specs_kept() -> None:
    assert not section_is_non_english(
        "The frequency response is 20 Hz to 20 kHz. The impedance is 32 ohms and "
        "the sensitivity is rated at 100 dB for this microphone capsule assembly."
    )


def test_english_specs_low_stopwords_kept() -> None:
    # A specs chapter: model numbers, units, terse labels — almost no
    # English function words AND no foreign ones. Sparse-English alone
    # would wrongly flag it; the foreign-evidence requirement keeps it.
    assert not section_is_non_english(
        "Model A diversity receiver. Model B stereo transmitter. "
        "Model C antenna combiner. Model D earphones. Pin assignment. "
        "Stereo jack plug, balanced audio loop output. "
        "Frequency range 470 608 MHz. RF output power 50 mW. "
        "Audio bandwidth 25 Hz 15 kHz. Weight 25 g. Dimensions 190 mm."
    )


def test_italian_prose_dropped() -> None:
    # Italian prose: foreign function words supply the positive evidence
    # the specs case lacks.
    assert section_is_non_english(
        "Congratulazioni e grazie per aver scelto questo prodotto. Il manuale "
        "contiene istruzioni importanti per la configurazione e il funzionamento "
        "del dispositivo. Si prega di leggere con attenzione le note seguenti."
    )
