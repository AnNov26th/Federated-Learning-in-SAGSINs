"""Post-decision evaluation only. No future labels are passed to inference."""

from backend.services.link_telemetry_service import telemetry


def evaluate_routes(result, research, nodes, size, event, load, predictive):
    def realized(route):
        access = route["access"]
        channel = {
            "id": 0,
            "distance": access["distance_km"],
            "bandwidth": access["features"]["bandwidth_mbps"],
            "latency": max(1, access["distance_km"] / 299.792458),
        }
        first = telemetry(
            channel, nodes[route["sourceId"]].type, research.sim_time_s + 1, size, load
        )["observed_delay_ms"]
        return (
            first
            + sum(hop["realized_next_tick_ms"] for hop in route["hops"])
            + (event["device"]["processing_ms"] if event["device"] else 0)
            + event["traffic"]["processing_ms"]
        )

    for route in (result["route"], result["baseline"]):
        app = route["application"]
        app["realized_next_tick_ms"] = realized(route)
        app["current_snapshot_one_way_ms"] = (
            route["total_static_transfer_ms"] + app["endpoint_processing_ms"]
        )
        channels = [route["access"]["features"]] + [
            hop["features"] for hop in route["hops"]
        ]
        app["serialization_ms"] = sum(
            size * 8 / (row["bandwidth_mbps"] * 1000) for row in channels
        )
        app["channel_latency_ms"] = (
            route["total_static_transfer_ms"] - app["serialization_ms"]
        )
        app["source"] = "shared_application_link_telemetry"
        app["note"] = (
            "Giả định link đối xứng; telemetry gồm truyền lan/xử lý, hàng đợi tổng hợp và tuần tự hóa theo dung lượng link. Ước tính FL dùng tick kế tiếp; công thức tĩnh dùng tick hiện tại. Chưa mô phỏng RF hay gói tin thực."
        )
        app["predicted_one_way_ms"] = (
            route["total_predicted_transfer_ms"] + app["endpoint_processing_ms"]
            if predictive
            else None
        )
        app["estimated_one_way_ms"] = (
            app["predicted_one_way_ms"]
            if predictive
            else app["current_snapshot_one_way_ms"]
        )
        app["latency_budget_met"] = (
            app["estimated_one_way_ms"] <= app["latency_budget_ms"]
        )
    result["comparison"] = {
        **result.get("comparison", {}),
        "realized_delay_change_ms": realized(result["baseline"])
        - realized(result["route"]),
        "application_estimate_change_ms": result["baseline"]["application"][
            "estimated_one_way_ms"
        ]
        - result["route"]["application"]["estimated_one_way_ms"],
        "evaluation_source": "shared_future_simulator_after_decision_not_measured_network",
    }
    result["delay_semantics"] = "application_link_one_way_ms"
    result["objective"] = result["objective"].replace("RTT_proxy_ms", "one_way_link_ms")
    result["destination"]["placement"] = "explicit_service_at_configured_edge"
    result["event_model"]["assumptions"] = [
        "Tầm truy cập và tốc độ thiết bị là giả định demo, không phải thông số chuẩn 4G/5G.",
        "Chỉ trạm ACCESS cung cấp truy cập; chỉ EDGE đặt dịch vụ. Các node khác chuyển tiếp trên link đã cấu hình.",
        "Telemetry và hàng đợi tổng hợp dùng chung cho huấn luyện/định tuyến; chưa mô phỏng gói tin, tranh chấp radio hay quỹ đạo liên tục.",
        "Phiên hữu hạn theo đồng hồ nghiên cứu; mất tuyến thì chờ/thử lại có thời hạn, hoàn tất hoặc hết hạn sẽ giải phóng băng thông.",
    ]
    result["allocation"][
        "policy"
    ] = "Chỉ giữ băng thông cho phiên đang truyền; hoàn tất, hết hạn hoặc mất tuyến sẽ giải phóng. Phiên chờ thử lại trên phần dung lượng còn lại."
    result["note"] = (
        "FL dự đoán độ trễ một chiều link ứng dụng tại tick kế tiếp; công thức tĩnh dùng tick hiện tại. Nhãn tương lai chỉ dùng đánh giá sau quyết định. Kênh/hàng đợi là mô phỏng."
    )
    if predictive:
        result["model_applicability"].update(
            training_payload_bytes="varied_application_packets",
            routing_end_to_end_validated=False,
            note="Mô hình cùng định nghĩa telemetry link/payload ứng dụng. Chưa kiểm chứng với mạng thật; sai số link không bảo đảm tuyến tối ưu.",
        )
