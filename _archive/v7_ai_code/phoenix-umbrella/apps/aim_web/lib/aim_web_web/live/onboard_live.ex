defmodule AimWebWeb.OnboardLive do
  @moduledoc """
  Guided onboarding wizard. Lists available templates, walks the user through
  questions, then shells out to `aim-onboard --non-interactive` to apply.

  Configuration:
      config :aim_web, AimWebWeb.OnboardLive,
        binary: "aim-onboard",
        templates_dir: "/opt/aim/templates",
        aim_root: "/var/lib/aim_fs"
  """
  use AimWebWeb, :live_view

  @impl true
  def mount(_params, session, socket) do
    cfg = Application.get_env(:aim_web, __MODULE__, [])
    binary = Keyword.get(cfg, :binary) || System.get_env("AIM_ONBOARD_BIN") || "aim-onboard"
    templates_dir =
      Keyword.get(cfg, :templates_dir) ||
        System.get_env("AIM_ONBOARD_TEMPLATES_DIR") ||
        "/opt/aim/templates"
    aim_root =
      Keyword.get(cfg, :aim_root) ||
        System.get_env("AIM_FS_ROOT") ||
        Path.expand("~/.aim_fs")

    tenant_id = session["user_id"] || "00000000-0000-0000-0000-000000000001"

    templates = list_templates(templates_dir)

    {:ok,
     socket
     |> assign(:binary, binary)
     |> assign(:templates_dir, templates_dir)
     |> assign(:aim_root, aim_root)
     |> assign(:tenant_id, tenant_id)
     |> assign(:available, templates)
     |> assign(:template, nil)
     |> assign(:questions, [])
     |> assign(:step, 0)
     |> assign(:answers, %{})
     |> assign(:outcome, nil)
     |> assign(:error, nil)}
  end

  @impl true
  def handle_event("pick_template", %{"path" => path}, socket) do
    case load_template(socket.assigns.binary, path) do
      {:ok, t} ->
        questions = filter_questions(t["questions"], %{})

        {:noreply,
         socket
         |> assign(:template, %{path: path, parsed: t})
         |> assign(:questions, questions)
         |> assign(:step, 0)
         |> assign(:answers, %{})
         |> assign(:outcome, nil)
         |> assign(:error, nil)}

      {:error, reason} ->
        {:noreply, assign(socket, :error, reason)}
    end
  end

  def handle_event("answer", params, socket) do
    q = Enum.at(socket.assigns.questions, socket.assigns.step)
    raw = Map.get(params, "value", "")
    a = decode_answer(q, raw)
    answers = Map.put(socket.assigns.answers, q["id"], a)

    next = socket.assigns.step + 1
    questions = filter_questions(socket.assigns.template.parsed["questions"], answers)

    {:noreply,
     socket
     |> assign(:answers, answers)
     |> assign(:questions, questions)
     |> assign(:step, next)}
  end

  def handle_event("submit", _, socket) do
    json = Jason.encode!(socket.assigns.answers)

    args = [
      "--template", socket.assigns.template.path,
      "--tenant-id", socket.assigns.tenant_id,
      "--aim-root", socket.assigns.aim_root,
      "--non-interactive"
    ]

    case System.cmd(socket.assigns.binary, args, input: json) do
      {out, 0} ->
        decoded =
          case Jason.decode(String.trim(out)) do
            {:ok, m} -> m
            _ -> %{"raw" => out}
          end

        {:noreply, assign(socket, :outcome, decoded)}

      {err, code} ->
        {:noreply, assign(socket, :error, "exit=#{code}: #{err}")}
    end
  rescue
    e -> {:noreply, assign(socket, :error, Exception.message(e))}
  end

  def handle_event("restart", _, socket) do
    {:noreply,
     socket
     |> assign(:template, nil)
     |> assign(:questions, [])
     |> assign(:step, 0)
     |> assign(:answers, %{})
     |> assign(:outcome, nil)
     |> assign(:error, nil)}
  end

  defp list_templates(dir) do
    case File.ls(dir) do
      {:ok, files} ->
        files
        |> Enum.filter(&String.ends_with?(&1, ".yaml"))
        |> Enum.sort()
        |> Enum.map(fn f -> %{name: f, path: Path.join(dir, f)} end)

      _ -> []
    end
  end

  defp load_template(binary, path) do
    case System.cmd(binary, ["--template", path, "--emit-template-json"]) do
      {out, 0} ->
        case Jason.decode(String.trim(out)) do
          {:ok, t} -> {:ok, t}
          {:error, e} -> {:error, "decode: #{inspect(e)}"}
        end
      {err, code} -> {:error, "binary exit=#{code}: #{err}"}
    end
  rescue
    e -> {:error, Exception.message(e)}
  end

  defp filter_questions(questions, answers) do
    Enum.filter(questions || [], fn q ->
      deps = Map.get(q, "depends_on", []) || []
      Enum.all?(deps, &dep_pass?(&1, answers))
    end)
  end

  defp dep_pass?(%{"field" => field} = dep, answers) do
    val = Map.get(answers, field)
    val_s = stringify_answer(val)

    cond do
      is_binary(dep["equals"]) -> val_s == dep["equals"]
      is_binary(dep["not_equals"]) -> val_s != dep["not_equals"]
      is_list(dep["in"]) -> Enum.member?(dep["in"], val_s)
      is_list(dep["not_in"]) -> not Enum.member?(dep["not_in"], val_s)
      true -> true
    end
  end

  defp stringify_answer(nil), do: ""
  defp stringify_answer(s) when is_binary(s), do: s
  defp stringify_answer(b) when is_boolean(b), do: to_string(b)
  defp stringify_answer(l) when is_list(l), do: Enum.join(l, ", ")
  defp stringify_answer(other), do: inspect(other)

  defp decode_answer(%{"type" => "list"}, raw) when is_binary(raw) do
    raw
    |> String.split(["\n", "\r\n"], trim: true)
    |> Enum.map(&String.trim/1)
    |> Enum.reject(&(&1 == ""))
  end
  defp decode_answer(%{"type" => "multi_choice"}, raw) when is_binary(raw) do
    raw
    |> String.split([" ", ","], trim: true)
    |> Enum.map(&String.trim/1)
    |> Enum.reject(&(&1 == ""))
  end
  defp decode_answer(%{"type" => "bool"}, raw) when is_binary(raw),
    do: raw in ["true", "yes", "y", "1", "on"]
  defp decode_answer(%{"type" => "number"}, raw) when is_binary(raw) do
    case Float.parse(raw) do
      {n, _} -> n
      :error -> raw
    end
  end
  defp decode_answer(_, raw), do: raw

  @impl true
  def render(assigns) do
    ~H"""
    <div class="onboard">
      <h1>AIM · Onboarding</h1>

      <%= if @error do %>
        <div class="error">⚠ <%= @error %></div>
      <% end %>

      <%= cond do %>
        <% @outcome != nil -> %>
          <div class="result">
            <h2>✓ Готово</h2>
            <p><strong>Папка:</strong> <code><%= @outcome["target_dir"] %></code></p>
            <p><strong>Файлов создано:</strong> <%= length(@outcome["files_written"] || []) %></p>
            <p><strong>Записей предложено:</strong> <%= length(@outcome["entities_proposed"] || []) %></p>
            <p><a href="/inbox">→ Открыть Inbox для approval</a></p>
            <button phx-click="restart">⟲ Создать ещё один</button>
          </div>

        <% @template == nil -> %>
          <h2>Выбери шаблон</h2>
          <ul class="tpl-list">
            <%= for t <- @available do %>
              <li>
                <button phx-click="pick_template" phx-value-path={t.path}>
                  <%= t.name %>
                </button>
              </li>
            <% end %>
            <%= if @available == [] do %>
              <li>(нет .yaml шаблонов в <code><%= @templates_dir %></code>)</li>
            <% end %>
          </ul>

        <% @step >= length(@questions) -> %>
          <h2><%= @template.parsed["title"] %></h2>
          <p>Все вопросы заданы. Применить?</p>
          <details>
            <summary>Ответы</summary>
            <pre><%= Jason.encode!(@answers, pretty: true) %></pre>
          </details>
          <button phx-click="submit">✓ Применить</button>
          <button phx-click="restart">⟲ Сначала</button>

        <% true -> %>
          <% q = Enum.at(@questions, @step) %>
          <h2><%= @template.parsed["title"] %> · вопрос <%= @step + 1 %>/<%= length(@questions) %></h2>
          <p class="prompt"><%= q["prompt"] %></p>
          <form phx-submit="answer">
            <%= cond do %>
              <% q["type"] == "choice" -> %>
                <%= for opt <- q["options"] do %>
                  <label><input type="radio" name="value" value={opt} /> <%= opt %></label><br/>
                <% end %>
              <% q["type"] == "multi_choice" -> %>
                <input type="text" name="value" placeholder="через пробел или запятую" />
                <small>options: <%= Enum.join(q["options"], ", ") %></small>
              <% q["type"] == "list" or q["multiline"] == true -> %>
                <textarea name="value" rows="6" placeholder="по строке"></textarea>
              <% q["type"] == "bool" -> %>
                <label><input type="checkbox" name="value" value="true" /> да</label>
              <% true -> %>
                <input type="text" name="value" />
            <% end %>
            <button type="submit">→ Далее</button>
          </form>
      <% end %>
    </div>

    <style>
      .onboard { max-width: 760px; margin: 1.5rem auto; font-family: system-ui; }
      .onboard h1 { font-size: 1.4rem; }
      .onboard .error { background: #fee; padding: .5rem; border: 1px solid #fcc; }
      .onboard ul.tpl-list { list-style: none; padding: 0; }
      .onboard ul.tpl-list li button { margin: .25rem 0; padding: .5rem .75rem; }
      .onboard form input[type=text], .onboard form textarea { width: 100%; }
      .onboard form button { margin-top: .5rem; }
      .onboard .result { padding: 1rem; border: 1px solid #ccc; border-radius: 6px; }
    </style>
    """
  end
end
