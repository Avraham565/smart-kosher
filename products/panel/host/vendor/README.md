# vendor/ — files copied from lvgl_micropython, not written here

`gt911_extension.py` is upstream's touch-config helper, taken verbatim from
`~/lvgl_micropython/api_drivers/common_api_drivers/indev/gt911_extension.py`.

It is **not** frozen into the firmware — `GT911.firmware_config()` raises
`ImportError('you need to upload the gt911_extension.py file to the MCU')` when
it is missing — so a run that wants to read or change the touch controller's
sensitivity has to put it on the board first.

It lives under `host/` rather than `device/` deliberately. `device/` is the
product: everything in it is deployed to every panel and is covered by the
payload-closure test in `tests/test_hwtest_payload_is_complete.py`. This file is
neither — it is a bench tool, uploaded by one probe and not part of what the
product runs. Putting it in `device/` would make it look like ours and would
put an upstream file under a test that derives its list from our imports.

Re-copy it if the lvgl_micropython checkout is updated; nothing here edits it.
