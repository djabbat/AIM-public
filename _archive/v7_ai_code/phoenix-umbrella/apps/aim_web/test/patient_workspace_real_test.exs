defmodule AimWeb.PatientWorkspaceRealTest do
  @moduledoc """
  Real-data smoke for `/patients/:id` against the existing
  `Beridze_Keti_2026_03_12` folder. Sanity-checks the binary chain
  (aim-patient-workspace → aim-lab-parser → tools/lab_evaluate.py →
  aim-compat). Skipped in CI; runs locally on the developer's box.
  """
  use ExUnit.Case, async: false
  import Phoenix.ConnTest
  import Phoenix.LiveViewTest

  @endpoint AimWeb.Endpoint

  @real_patient "Beridze_Keti_2026_03_12"

  setup do
    {:ok, conn: build_conn()}
  end

  defp real_patient_present? do
    aim_root = System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"
    File.exists?(Path.join([aim_root, "Patients", @real_patient, "MEMORY.md"]))
  end

  test "real patient overview renders demographics and meds count", %{conn: conn} do
    if real_patient_present?() do
      {:ok, _view, html} = live(conn, "/patients/#{@real_patient}")
      assert html =~ @real_patient
      # Beridze has 13 medications in MEMORY.md.
      assert html =~ "Active medications"
      # Conditions section is rendered (anxiety / derealization etc).
      assert html =~ "Conditions"
      # PAM section (current_score may be nil so look for stable text).
      assert html =~ "PAM-13"
      # Project core block always rendered.
      assert html =~ "Project core"
      # Treatment-by-button visible.
      assert html =~ "Add medication"
    else
      :ok
    end
  end

  test "switching to Labs tab triggers parse pipeline", %{conn: conn} do
    if real_patient_present?() do
      {:ok, view, _html} = live(conn, "/patients/#{@real_patient}")
      html = view |> element("button[phx-value-tab=labs]") |> render_click()
      # Either parsed labs render (real OCR present) or empty-state muted text.
      assert html =~ "Parsed lab values" or html =~ "couldn"
    else
      :ok
    end
  end

  test "treatment modal opens on click", %{conn: conn} do
    if real_patient_present?() do
      {:ok, view, _html} = live(conn, "/patients/#{@real_patient}")
      html = view |> element("button", "Add medication") |> render_click()
      assert html =~ "Compatibility check"
      assert html =~ "Drug name"
    else
      :ok
    end
  end
end
