defmodule AimWeb.I18nTest do
  use ExUnit.Case, async: true
  alias AimWeb.I18n

  test "covers all 7 locales" do
    expected = ~w(en fr es ru zh ar ka)a
    assert Enum.sort(I18n.locales()) == Enum.sort(expected)
  end

  test "default is :en" do
    assert I18n.default() == :en
  end

  test "translate returns localised string" do
    assert I18n.t("nav.home", :en) == "Home"
    assert I18n.t("nav.home", :ru) == "Главная"
    assert I18n.t("nav.home", :ka) == "მთავარი"
    assert I18n.t("nav.home", :ar) == "الرئيسية"
    assert I18n.t("nav.home", :zh) == "首页"
  end

  test "unknown key falls back to itself" do
    assert I18n.t("nav.does_not_exist", :en) == "nav.does_not_exist"
  end

  test "unknown locale falls back to default value" do
    assert I18n.t("nav.home", :xx) == "Home"
  end

  test "rtl? identifies arabic" do
    assert I18n.rtl?(:ar)
    refute I18n.rtl?(:en)
    refute I18n.rtl?(:ka)
  end

  test "parse handles strings, hyphenated tags, atoms" do
    assert I18n.parse("ru") == :ru
    assert I18n.parse("en-US") == :en
    assert I18n.parse("garbage-locale") == :en   # default
    assert I18n.parse(:ar) == :ar
    assert I18n.parse(:invalid) == :en
    assert I18n.parse(nil) == :en
  end

  test "all keys present for all locales" do
    keys = ~w(app.title nav.home nav.chat nav.intake nav.cases nav.consult
              home.heading home.tagline chat.heading chat.todo
              intake.heading cases.heading case.heading common.todo lang.label)
    for k <- keys, l <- I18n.locales() do
      v = I18n.t(k, l)
      refute v == k, "missing translation: #{k}/#{l}"
      assert is_binary(v)
    end
  end
end
