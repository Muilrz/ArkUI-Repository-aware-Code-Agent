"""A minimal, disposable C++ repository fixture for repository tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


_HEADER = """\
#pragma once

namespace fixture {

class Widget {
public:
    virtual ~Widget() = default;
    int value() const;
};

class DerivedWidget : public Widget {
public:
    int doubled_value() const;
};

}  // namespace fixture
"""

_SOURCE = """\
#include "fixture/widget.h"

namespace fixture {

int Widget::value() const
{
    return 21;
}

int DerivedWidget::doubled_value() const
{
    return value() * 2;
}

}  // namespace fixture
"""

_TEST_SOURCE = """\
#include "fixture/widget.h"

#define HWTEST_F(fixture, name, level) void fixture##_##name()
#define TEST_F(fixture, name) void fixture##_##name()

class WidgetTest {};
class AlternateWidgetTest {};

HWTEST_F(WidgetTest, ValueIsTwentyOne, TestSize.Level1)
{
    fixture::Widget widget;
    (void)widget.value();
}

TEST_F(WidgetTest, DerivedWidgetDoublesValue)
{
    fixture::DerivedWidget widget;
    (void)widget.doubled_value();
}

HWTEST_F(AlternateWidgetTest, DerivedWidgetDoublesValue, TestSize.Level1)
{
    fixture::DerivedWidget widget;
    (void)widget.doubled_value();
}
"""


@dataclass(frozen=True, slots=True)
class SyntheticCppRepository:
    """Paths belonging to one isolated synthetic C++ repository."""

    root: Path
    header: Path
    source: Path
    test_source: Path

    @property
    def relative_files(self) -> tuple[Path, ...]:
        """Return the fixture's files relative to its repository root."""

        return tuple(
            path.relative_to(self.root)
            for path in (self.header, self.source, self.test_source)
        )


@contextmanager
def synthetic_cpp_repository() -> Iterator[SyntheticCppRepository]:
    """Create an isolated repository and remove it after the context exits."""

    with TemporaryDirectory(prefix="repository-agent-fixture-") as temporary_root:
        root = Path(temporary_root).resolve()
        header = root / "include" / "fixture" / "widget.h"
        source = root / "src" / "widget.cpp"
        test_source = root / "tests" / "widget_test.cpp"

        for path, content in (
            (header, _HEADER),
            (source, _SOURCE),
            (test_source, _TEST_SOURCE),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        yield SyntheticCppRepository(
            root=root,
            header=header,
            source=source,
            test_source=test_source,
        )
