from __future__ import annotations

import copy
import unittest
from unittest import mock

from backend import k8s_client, paper_jobs, scheduling as s


def node(name="edge-1", **overrides):
    return {
        "name": name, "hostname": name, "arch": "amd64", "os": "linux", "node_type": "edge",
        "internal_ip": "192.0.2.1",
        "ready": "True", "unschedulable": False, "taints": [], "images": [],
        "allocatable": {"cpu": "4", "memory": "8Gi", s.GPU: "0", "pods": "10", "ephemeral-storage": "10Gi"},
        **overrides,
    }


def state(nodes=None, pods=None, quotas=None, limits=None):
    result = s.snapshot(nodes or [node()], pods or [], quotas or [], limits or [], "smart-kube")
    result["observed_at"] = 123
    return result


class SchedulingTest(unittest.TestCase):
    def select(self, snapshot, gpu=0, **kwargs):
        req, lim = s.requirements("500m", "512Mi", gpu)
        return s.select(snapshot, req, lim, kwargs.pop("image", "python:3.11-slim"), **kwargs)

    def test_label_and_capacity_do_not_grant_gpu(self):
        n = node(labels={"nvidia.com/gpu.present": "true"}, capacity={s.GPU: "8"})
        n["allocatable"].pop(s.GPU)
        with self.assertRaisesRegex(RuntimeError, "insufficient nvidia.com/gpu"):
            self.select(state([n]), gpu=1)
        self.assertEqual(k8s_client._node_gpu_capacity({"capacity": {s.GPU: "8"}}), 0)

    def test_hostname_never_bypasses_health_cordon_taints_or_arch(self):
        for changes in ({"ready": "Unknown"}, {"unschedulable": True},
                        {"taints": [{"key": "dedicated", "effect": "NoSchedule"}]},
                        {"arch": "arm64"}, {"conditions": [{"type": "DiskPressure", "status": "True"}]}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.select(state([node(**changes)]), hostname="edge-1", arch="amd64")

    def test_all_namespace_pods_and_pending_reservations_consume_gpu(self):
        n = node()
        n["allocatable"][s.GPU] = "2"
        pods = [{"metadata": {"namespace": "other"}, "spec": {"nodeName": n["name"], "containers": [
            {"resources": {"limits": {s.GPU: "1"}}}
        ]}, "status": {"phase": "Running"}}, {
            "metadata": {"annotations": {"smartkube/selected-node": n["name"]}},
            "spec": {"containers": [{"resources": {"limits": {s.GPU: "1"}}}]},
            "status": {"phase": "Pending"},
        }]
        with self.assertRaisesRegex(RuntimeError, "available 0"):
            self.select(state([n], pods), gpu=1)
        pods[1]["status"]["phase"] = "Succeeded"
        self.select(state([n], pods), gpu=1)

    def test_init_sidecars_overhead_and_quantities(self):
        requests = s.pod_requests({"spec": {
            "containers": [{"resources": {"requests": {"cpu": "250m", "memory": "128Mi"}}}],
            "initContainers": [
                {"restartPolicy": "Always", "resources": {"requests": {"cpu": "100m"}}},
                {"resources": {"requests": {"cpu": "2", "memory": "1Gi"}}},
            ], "overhead": {"cpu": "50m"},
        }})
        self.assertEqual(requests["cpu"], s.quantity("2150m"))
        self.assertEqual(requests["memory"], s.quantity("1Gi"))

    def test_batch_overcommit_rejected_before_creation(self):
        rows = [{"tier": "edge", "count": 3, "arch": "amd64", "cpu": "2", "memory": "1Gi", "gpu": 0, "image": "python:3.11-slim"}]
        with mock.patch.object(k8s_client, "scheduling_snapshot", return_value=state()), mock.patch.object(k8s_client, "create_ssh_pod") as create:
            with self.assertRaisesRegex(RuntimeError, "insufficient cpu"):
                paper_jobs._schedule({}, 1, {"resources": rows}, 1, "task")
            create.assert_not_called()

    def test_quota_batch_and_limit_range(self):
        quota = {"metadata": {"name": "budget"}, "status": {"hard": {"requests.cpu": "1"}, "used": {"requests.cpu": "0"}}}
        cluster = state(quotas=[quota])
        self.select(cluster, reserve=True)
        self.select(cluster, reserve=True)
        with self.assertRaisesRegex(RuntimeError, "ResourceQuota budget"):
            self.select(cluster, reserve=True)
        limits = [{"spec": {"limits": [{"type": "Container", "max": {"memory": "256Mi"}}]}}]
        with self.assertRaisesRegex(RuntimeError, "LimitRange"):
            self.select(state(limits=limits))

    def test_limit_defaults_count_against_storage(self):
        limits = [{"spec": {"limits": [{"type": "Container", "defaultRequest": {"ephemeral-storage": "20Gi"}}]}}]
        with self.assertRaisesRegex(RuntimeError, "insufficient ephemeral-storage"):
            self.select(state(limits=limits))

    def test_scoped_quota_does_not_block_unrelated_pods(self):
        quota = {"metadata": {"name": "batch"}, "spec": {"scopes": ["Terminating"]},
                 "status": {"hard": {"pods": "0"}, "used": {}}}
        self.select(state(quotas=[quota]))
        quota["spec"]["scopes"] = ["NotTerminating"]
        with self.assertRaisesRegex(RuntimeError, "ResourceQuota batch"):
            self.select(state(quotas=[quota]))

    def test_zero_gpu_does_not_add_a_gpu_limit_to_cpu_workloads(self):
        req, lim = s.requirements("500m", "512Mi")
        self.assertNotIn(s.GPU, req)
        self.assertNotIn(s.GPU, lim)

    def test_cuda_cannot_run_without_gpu_or_on_unvalidated_jetson(self):
        with self.assertRaisesRegex(RuntimeError, "explicit GPU request"):
            self.select(state(), image=k8s_client.GPU_IMAGE)
        n = node(arch="arm64")
        n["allocatable"][s.GPU] = "1"
        with self.assertRaisesRegex(RuntimeError, "Jetson"):
            self.select(state([n]), gpu=1, image=k8s_client.GPU_IMAGE)

    def test_fallback_preserves_gpu_and_architecture(self):
        with mock.patch.object(k8s_client, "scheduling_snapshot", return_value=state()):
            selected, _ = k8s_client._select_node_with_fallback("amd64", None, "cloud", 1, True)
        self.assertIsNone(selected)
        cloud = node("cloud-1", node_type="cloud")
        cloud["allocatable"][s.GPU] = "1"
        with mock.patch.object(k8s_client, "scheduling_snapshot", return_value=state([cloud])):
            selected, selection = k8s_client._select_node_with_fallback("amd64", None, "edge", 1, True)
        self.assertEqual(selected["name"], "cloud-1")
        self.assertEqual(selection["effective"]["gpu"], 1)
        self.assertEqual(selection["relaxed"], ["node_type"])

    def test_known_node_proxy_failure_blocks_uncached_registry_images(self):
        pod = {"spec": {"nodeName": "edge-1", "containers": []}, "status": {
            "phase": "Pending", "containerStatuses": [{"image": "ubuntu:22.04", "state": {
                "waiting": {"reason": "ImagePullBackOff", "message": "proxyconnect tcp: connection refused"}
            }}]
        }}
        with self.assertRaisesRegex(RuntimeError, "registry unreachable"):
            self.select(state(pods=[pod]))
        self.select(state([node(images=["docker.io/library/python:3.11-slim"])], [pod]))

    def test_spec_uses_scheduler_affinity_instead_of_node_name(self):
        spec = k8s_client._build_pod_spec([], "Never", "edge-1", "amd64", node())
        self.assertIsNone(spec.node_name)
        terms = spec.affinity.node_affinity.required_during_scheduling_ignored_during_execution.node_selector_terms
        self.assertEqual(terms[0].match_fields[0].values, ["edge-1"])

    def test_preflight_failure_precedes_port_allocation_and_pod_creation(self):
        with mock.patch.object(k8s_client, "ensure_namespace"), mock.patch.object(k8s_client, "scheduling_snapshot", return_value=state()), mock.patch.object(k8s_client, "_allocate_ssh_port") as allocate, mock.patch.object(k8s_client.core_v1, "create_namespaced_pod") as create:
            with self.assertRaisesRegex(RuntimeError, "insufficient nvidia.com/gpu"):
                k8s_client.create_ssh_pod({"id": 1, "username": "test"}, gpu=1)
            allocate.assert_not_called()
            create.assert_not_called()

    def test_explicit_gpu_runtime_is_preserved_in_created_pod(self):
        n = node()
        n["allocatable"][s.GPU] = "1"
        with mock.patch.object(k8s_client, "ensure_namespace"), mock.patch.object(k8s_client, "scheduling_snapshot", return_value=state([n])), mock.patch.object(k8s_client, "_allocate_ssh_port", return_value=31000), mock.patch.object(k8s_client.core_v1, "create_namespaced_pod") as create, mock.patch.object(k8s_client.core_v1, "create_namespaced_service"):
            result = k8s_client.create_ssh_pod({"id": 1, "username": "test"}, gpu=1, image="python:3.11-slim")
        self.assertEqual(result["image"], "python:3.11-slim")
        pod = create.call_args.args[1]
        self.assertEqual(pod.spec.containers[0].image, result["image"])
        self.assertEqual(pod.spec.containers[0].resources.limits[s.GPU], "1")
        self.assertEqual(pod.metadata.annotations["smartkube/selected-node"], n["name"])
        self.assertEqual(create.call_args_list[0].kwargs["dry_run"], "All")

    def test_read_failure_never_falls_back_to_unchecked_placement(self):
        with mock.patch.object(k8s_client, "scheduling_snapshot", side_effect=RuntimeError("cluster read denied")):
            with self.assertRaisesRegex(RuntimeError, "cluster read denied"):
                k8s_client._select_node_with_fallback(None, None, None, 0, True)

    def test_config_agent_receives_live_cluster(self):
        cluster = state()
        generated = {"resources": [], "workflow_steps": [], "analysis_plan": [], "assumptions": [], "agent_trace": {}}
        workspace = {"mode": "full", "experiment_id": 1, "experiment_name": "test", "goal": "test"}
        with mock.patch.object(k8s_client, "scheduling_snapshot", return_value=cluster), mock.patch.object(paper_jobs, "_infer_resources", return_value=({}, [])), mock.patch.object(paper_jobs.paper_agents, "run_config_agent", return_value=generated) as agent:
            result = paper_jobs._build_configuration(workspace, [], {"agent_trace": {}})
        self.assertEqual(agent.call_args.args[2]["cluster"]["nodes"][0]["available"][s.GPU], "0")
        self.assertEqual(result["cluster_snapshot"]["observed_at"], 123)

    def test_runtime_alignment_preserves_gpu_request_and_python(self):
        config = {"resources": [{"tier": "cloud", "image": k8s_client.GPU_IMAGE, "gpu": 1}]}
        program = {"runtime": {"image": "python:3.11-slim"}, "agent_trace": {}}
        aligned = paper_jobs._align_configuration_runtime(copy.deepcopy(config), program)
        self.assertEqual(aligned["resources"][0]["image"], "python:3.11-slim")
        self.assertEqual(aligned["resources"][0]["gpu"], 1)

    def test_wait_reports_pull_failure_without_timeout(self):
        with mock.patch.object(k8s_client, "describe_pod", return_value={"phase": "Pending", "container_statuses": [{"reason": "ImagePullBackOff", "message": "proxy refused"}]}):
            with self.assertRaisesRegex(RuntimeError, "proxy refused"):
                paper_jobs._wait_for_pod_ready("test")

    def test_oneshot_waits_for_main_and_cleans_up_on_pull_failure(self):
        from kubernetes import client
        pending = client.V1Pod(status=client.V1PodStatus(phase="Running", container_statuses=[
            client.V1ContainerStatus(name="main", image="python", image_id="", ready=False, restart_count=0,
                                     state=client.V1ContainerState(waiting=client.V1ContainerStateWaiting(reason="ImagePullBackOff", message="proxy refused")))
        ]))
        with mock.patch.object(k8s_client, "ensure_namespace"), mock.patch.object(k8s_client, "scheduling_snapshot", return_value=state()), mock.patch.object(k8s_client.core_v1, "create_namespaced_pod"), mock.patch.object(k8s_client.core_v1, "read_namespaced_pod", return_value=pending), mock.patch.object(k8s_client.core_v1, "delete_namespaced_pod") as delete, mock.patch.object(k8s_client, "copy_to_pod") as upload:
            with self.assertRaisesRegex(RuntimeError, "proxy refused"):
                k8s_client.run_python_oneshot({"id": 1, "username": "test"}, "/tmp/example.py")
            upload.assert_not_called()
            delete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
