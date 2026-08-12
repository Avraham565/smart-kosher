idf_component_register(
    SRCS "main.c" "link.c" "zb.c" "protocol.c" "txn.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES nvs_flash driver json vfs esp_timer
)
