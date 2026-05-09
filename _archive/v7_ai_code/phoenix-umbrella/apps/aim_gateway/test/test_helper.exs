{:ok, _} = Application.ensure_all_started(:aim_memory)
{:ok, _} = Application.ensure_all_started(:plug)
ExUnit.start()
