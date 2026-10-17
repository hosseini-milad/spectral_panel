EXCLUDED_FIELDS = [
    "_id", "source_file", "source_path", "created_at",
    "timestamp", "flow_start", "window_start", "source_day", "row_index",
    "original_id", "ingestion_id", "source_type", "type",
    "label_binary", "label_multiclass", "source_label", "source_label_binary",
    "source_label_multiclass",
    "attack_category", "attack_type",
]
LABEL_FIELD = "label"

PASSTHROUGH_FIELDS = {"attack_category", "attack_type"}

# These values already have a bounded meaning and should remain categorical/binary.
BINARY_FIELDS = {
    "label", "label_binary", "flag_ack", "flag_fin", "flag_psh", "flag_rst",
    "flag_syn", "flag_urg", "is_encrypted_port", "is_syn_only",
    "proto_icmp", "proto_tcp", "proto_udp",
}
