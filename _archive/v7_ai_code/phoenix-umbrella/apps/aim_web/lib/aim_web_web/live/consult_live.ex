defmodule AimWeb.ConsultLive do
  @moduledoc """
  Public-facing consultation booking page (Georgian).
  Static info for Tkemaladze remote consultation flow.
  """
  use AimWeb, :live_view

  @stages [
    %{
      n: "I",
      title: "I კონსულტაცია (70 ლარი)",
      body: "დადგინდება, რა ანალიზებია საჭირო."
    },
    %{
      n: "II",
      title: "II კონსულტაცია (70 ლარი)",
      body: "ანალიზების საფუძველზე დაგიწერთ პერსონალიზირებულ დანიშნულებას."
    },
    %{
      n: "III",
      title: "III კონსულტაცია (70 ლარი)",
      body:
        "1 თვის შემდეგ — მკურნალობის შედეგების მონიტორინგი. გამოვკითხავ ცვლილებებს, " <>
          "დავაზუსტებ ანამნეზს. საჭიროების შემთხვევაში დავადგენ ახალ ანალიზებს."
    },
    %{
      n: "IV",
      title: "IV კონსულტაცია (70 ლარი)",
      body: "ახალი ანალიზების საფუძველზე დაგიწერთ პერსონალიზირებულ დანიშნულებას."
    }
  ]

  @notes [
    "ახალ ანალიზებს ვნიშნავ მხოლოდ საჭიროების შემთხვევაში.",
    "რაიმეს დასაზუსტებლად მომწერეთ Telegram-ზე."
  ]

  @bank [
    %{name: "საქართველოს ბანკი", iban: "GE49BG0000000101452713"},
    %{name: "TBC", iban: "GE66TB7820845064300007"}
  ]

  def mount(_params, _session, socket) do
    {:ok,
     assign(socket,
       page_title: "კონსულტაცია",
       stages: @stages,
       notes: @notes,
       bank: @bank,
       telegram: "+995 555 185 161"
     )}
  end

  def render(assigns) do
    ~H"""
    <section class="consult">
      <h1>დისტანციურად, ონლაინ ვმუშაობ მთელი მსოფლიოს მასშტაბით</h1>
      <p>
        Telegram:
        <a href={"https://t.me/" <> String.replace(@telegram, ~r/[^0-9]/, "")}>
          <%= @telegram %>
        </a>
      </p>

      <ol class="stages">
        <li :for={s <- @stages}>
          <h3><%= s.title %></h3>
          <p><%= s.body %></p>
        </li>
      </ol>

      <ul class="notes">
        <li :for={n <- @notes}>📌 <%= n %></li>
      </ul>

      <h2>რეკვიზიტები</h2>
      <ul class="bank">
        <li :for={b <- @bank}>
          <strong><%= b.name %>:</strong> <code><%= b.iban %></code>
        </li>
      </ul>
    </section>
    """
  end
end
