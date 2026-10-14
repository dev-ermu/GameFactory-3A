"""Tripo 骨骼绑定、重定向与格式转换封装（腾讯云 TokenHub 网关）。

这四个能力原本各自独立封装，这里共用一个中间基类：它们走同一套
"提交任务 → 轮询 → 下载"流程，只是端点与载荷不同。

参考来源：https://developers.tripo3d.com/zh/docs/sdk
TokenHub 网关下的两个端点：
    POST /v3/animations/rig        绑定骨骼
    POST /v3/animations/retarget   应用预设动画

Base URL 由用户在 `.env` 中填写，原样传入（规范 R6.4）。

服务端生成结果的可复现性无法保证（规范 R3.4）。
"""

import asyncio
import json

import httpx2
import math
import re
import struct

from models.base import BaseModel
from models.common import errors

# `rig_type` 取值：优先用骨骼检查接口返回的结果，不要猜；默认是 biped。
RIG_TYPES = frozenset(
    {"biped", "quadruped", "hexapod", "octopod", "avian", "serpentine", "aquatic"}
)

# 骨骼命名规范。mixamo 仅供 DCC 导入：动画重定向接口拒绝 mixamo 命名的骨架。
RIG_SPECS = frozenset({"tripo", "mixamo"})

# 动画接口唯一接受的命名规范。
ANIMATABLE_SPEC = "tripo"

# 双足骨架（RIG V2.5）可用的预设动画。
BIPED_PRESETS = frozenset(
    {
        "preset:idle", "preset:walk", "preset:run", "preset:dive", "preset:climb",
        "preset:jump", "preset:slash", "preset:shoot", "preset:hurt", "preset:fall",
        "preset:turn",
    }
)

# 每种非双足拓扑各自唯一提供的预设动画，按 `rig_type` 索引。
NON_BIPED_PRESETS = {
    "quadruped": "preset:quadruped:walk",
    "hexapod": "preset:hexapod:walk",
    "octopod": "preset:octopod:walk",
    "serpentine": "preset:serpentine:march",
    "aquatic": "preset:aquatic:march",
}

# 预设动画必须与骨架拓扑匹配，服务端会拒绝不匹配的组合。
PRESET_ANIMATIONS = BIPED_PRESETS | frozenset(NON_BIPED_PRESETS.values())

# rig-check 对无法归类骨架的网格返回该值；它不是 `rig_type` 的合法取值。
UNCLASSIFIED = "others"


def default_preset(rig_type: str) -> str:
    """返回该骨架拓扑对应的行走类预设动画。

    Args:
        rig_type: 骨架类型，例如 `biped` 或 `quadruped`。

    Returns:
        预设动画名称；未收录的类型回退到 `preset:walk`。
    """
    return NON_BIPED_PRESETS.get(str(rig_type).strip().lower(), "preset:walk")


class _TokenHubTaskModel(BaseModel):
    """TokenHub 上的任务型模型共用逻辑。"""

    provider = "tokenhub"
    display_name = "TokenHub"

    # 端点路径，由各子类指定。
    endpoint: str = ""

    # 该能力对应的模型版本，由各子类指定。
    default_model_id: str = ""

    def __init__(
        self,
        model_id: str,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: int = 1800,
        poll_interval: float = 10.0,
        max_retries: int = 3,
        output_format: str = "glb",
        verbose: bool = False,
    ) -> None:
        """保存通用参数，其余由子类追加。"""
        super().__init__(
            model_id or self.default_model_id,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
            output_format=output_format,
            verbose=verbose,
        )

    def credential_spec(self) -> tuple[str, str]:
        """返回 TokenHub 需要的配置项名。"""
        return ("tokenhub_api_key", "tokenhub_api_base")

    def request(self, *args, **kwargs) -> bytes:
        """由子类实现具体的任务提交逻辑。"""
        pass

    async def _run_json(self, payload: dict) -> dict:
        """提交任务并返回解析后的结果字典，不下载文件。"""
        client = self.http_client()
        body = self.call_with_retry(
            lambda: client.post(self.endpoint, json=self._with_model(payload))
        )

        data = self._unwrap(body)
        task_id = str(data.get("id") or data.get("task_id") or "")

        if not task_id:
            raise errors.CloudModelServerError(
                f"{self.display_name} 响应中没有任务标识：{data}"
            )

        self.bind_session(task_id)
        finished = self.call_with_retry(lambda: self._fetch(client, task_id))
        self._assert_success(finished, task_id)

        return finished

    async def _run_bytes(self, payload: dict) -> dict:
        """提交任务、等待完成并下载产物，返回含字节的字典。"""
        client = self.http_client()
        body = self.call_with_retry(
            lambda: client.post(self.endpoint, json=self._with_model(payload))
        )

        data = self._unwrap(body)
        task_id = str(data.get("id") or data.get("task_id") or "")

        if not task_id:
            raise errors.CloudModelServerError(
                f"{self.display_name} 响应中没有任务标识：{data}"
            )

        self.bind_session(task_id)
        finished = self.call_with_retry(lambda: self._fetch(client, task_id))
        self._assert_success(finished, task_id)

        url = self._result_url(finished)

        if not url:
            raise errors.CloudTaskError(
                f"{self.display_name} 任务 {task_id} 没有返回结果地址"
            )

        payload_bytes = await asyncio.to_thread(self._download, url)

        return {"file_bytes": payload_bytes, "task_id": task_id}

    def _assert_success(self, finished: dict, task_id: str) -> None:
        """校验任务是否成功，否则抛出异常。"""
        state = str(finished.get("status", "")).lower()

        if state in ("success", "succeeded", "completed", "done"):
            return

        reason = str(
            finished.get("error")
            or finished.get("message")
            or finished.get("status")
            or "服务端未说明原因"
        )

        raise errors.CloudTaskError(f"{self.display_name} 任务 {task_id} 失败：{reason}")

    def _with_model(self, payload: dict) -> dict:
        """把模型标识写进请求体。"""
        return {"model": self.model_id, **payload}

    def _unwrap(self, body) -> dict:
        """解析 JSON 响应体，并把失败状态映射为对应异常。"""
        status = int(body.status_code)
        text = body.text or ""

        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError:
            data = {}

        if 200 <= status < 300:
            return data.get("data", data)

        reason = str(data.get("message") or text[:200])

        if status in (400, 422):
            raise errors.CloudModelRequestError(
                f"{self.display_name} 拒绝了该请求：{reason}"
            )

        if status == 402:
            raise errors.CloudModelQuotaError(f"{self.display_name} 额度不足：{reason}")

        if status in (401, 403):
            if "余额" in reason or "欠费" in reason:
                raise errors.CloudModelQuotaError(f"{self.display_name} 额度不足：{reason}")
            raise errors.CloudModelAuthError(f"{self.display_name} 鉴权失败：{reason}")

        if status == 429:
            raise errors.CloudModelRateLimitError(f"{self.display_name} 触发限流：{reason}")

        if status >= 500:
            raise errors.CloudModelServerError(
                f"{self.display_name} 服务端错误 {status}：{reason}"
            )

        raise errors.CloudModelRequestError(
            f"{self.display_name} 返回未预期的状态 {status}：{reason}"
        )

    def _fetch(self, client, task_id: str) -> dict:
        """查询任务状态，返回解析后的响应体。"""
        response = client.get(f"{self.endpoint}/{task_id}")

        return json.loads(response.text or "{}").get("data", {})

    def _result_url(self, data: dict) -> str:
        """从任务结果中取出下载地址。"""
        return str(data.get("output", {}).get("model") or data.get("model_url") or "")

    def _download(self, url: str) -> bytes:
        """下载结果文件，失败时归类为可重试的网络故障。"""
        try:
            with httpx2.Client(timeout=300.0, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.content
        except errors.CloudModelError:
            raise
        except Exception as exc:
            raise errors.CloudModelNetworkError(
                f"下载 {self.display_name} 结果失败：{exc}"
            ) from exc

class TripoRigCheckModel(_TokenHubTaskModel):
    """检查模型是否适合绑定骨骼。"""

    display_name = "Tripo 骨骼适用性检查"
    endpoint = "/v3/animations/rig_check"
    default_model_id = "tripo-3d-rigging-check"

    def request(
        self,
        mesh: bytes | None = None,
        mesh_format: str = ".glb",
        mesh_url: str = "",
    ) -> dict:
        """检查给定网格能否绑定骨骼。

        Args:
            mesh: 网格文件的字节内容；与 `mesh_url` 至少给一个。
            mesh_format: 网格格式标记，例如 `.glb`。
            mesh_url: 已上传网格的地址；与 `mesh` 至少给一个。

        Returns:
            形如 `{"riggable": bool, "reason": str}` 的字典。
        """
        if not mesh and not mesh_url:
            raise ValueError("骨骼适用性检查需要 mesh 或 mesh_url")

        payload = {"format": mesh_format, "url": mesh_url}

        if mesh:
            payload["mesh"] = mesh

        return asyncio.run(self._run_json(payload))


class TripoRiggingModel(_TokenHubTaskModel):
    """为网格绑定骨骼。"""

    display_name = "Tripo 骨骼绑定"
    endpoint = "/v3/animations/rig"
    default_model_id = "tripo-3d-rigging"

    def request(
        self,
        mesh: bytes | None = None,
        mesh_format: str = ".glb",
        seed: int = 42,
        mesh_url: str = "",
        rig_type: str = "",
        rig_spec: str = "",
        out_format: str = "glb",
    ) -> dict:
        """绑定骨骼并返回带骨骼的模型。

        Args:
            mesh: 待绑定的网格字节内容；与 `mesh_url` 至少给一个。
            mesh_format: 网格格式标记，例如 `.glb`。
            seed: 随机种子，会透传给服务端，但不保证结果可复现。
            mesh_url: 已上传网格的地址。
            rig_type: 骨架类型，例如 `human`。
            rig_spec: 骨架规格的附加说明。
            out_format: 输出容器格式，例如 `glb` 或 `fbx`。

        Returns:
            含 `file_bytes` 的字典，产物字节放在该键下。
        """
        if not mesh and not mesh_url:
            raise ValueError("骨骼绑定需要 mesh 或 mesh_url")

        payload = {
            "format": mesh_format,
            "url": mesh_url,
            "seed": seed,
            "rig_type": rig_type,
            "rig_spec": rig_spec,
            "out_format": out_format,
        }

        if mesh:
            payload["mesh"] = mesh

        self.output_format = out_format

        return asyncio.run(self._run_bytes(payload))


class TripoAnimationModel(_TokenHubTaskModel):
    """把预设动画重定向到已有骨骼。"""

    display_name = "Tripo 动画重定向"
    endpoint = "/v3/animations/retarget"
    default_model_id = "tripo-3d-animation"

    def request(
        self,
        rig_task_id: str = "",
        animation: str = "",
        seed: int = 42,
        out_format: str = "fbx",
        animate_in_place: bool = True,
    ) -> dict:
        """应用预设动画并返回写入动画后的模型。

        Args:
            rig_task_id: 骨骼绑定任务标识。
            animation: 预设动画名称。
            seed: 随机种子，会透传给服务端，但不保证结果可复现。
            out_format: 输出容器格式，例如 `fbx`。
            animate_in_place: 是否原地写入动画，保留根位移。

        Returns:
            含 `file_bytes` 的字典，产物字节放在该键下。
        """
        if not rig_task_id or not animation:
            raise ValueError("动画重定向需要 rig_task_id 与 animation")

        payload = {
            "original_model_task_id": rig_task_id,
            "animation": animation,
            "seed": seed,
            "out_format": out_format,
            "animate_in_place": animate_in_place,
        }

        self.output_format = out_format

        return asyncio.run(self._run_bytes(payload))


class TripoFormatModel(_TokenHubTaskModel):
    """转换已生成模型的导出格式。"""

    display_name = "Tripo 格式转换"
    endpoint = "/v3/model/convert"
    default_model_id = "tripo-3d-format"

    # 服务商支持的导出格式。
    SUPPORTED_FORMATS = ("GLTF", "USDZ", "FBX", "OBJ", "STL", "3MF")

    def request(
        self,
        mesh: bytes | None = None,
        mesh_format: str = ".glb",
        seed: int = 42,
        mesh_url: str = "",
        output_format: str = "fbx",
    ) -> dict:
        """转换模型格式并返回结果。

        Args:
            mesh: 待转换的模型字节内容；与 `mesh_url` 至少给一个。
            mesh_format: 输入模型的格式标记。
            seed: 为插槽兼容而保留，服务商不支持该参数，会被忽略。
            mesh_url: 已上传模型的地址。
            output_format: 目标容器格式，例如 `fbx`。

        Returns:
            含 `file_bytes` 的字典，产物字节放在该键下。
        """
        del seed

        if not mesh and not mesh_url:
            raise ValueError("格式转换需要 mesh 或 mesh_url")

        target = output_format.upper()

        if target not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"output_format 只支持 {self.SUPPORTED_FORMATS}，收到 {output_format!r}"
            )

        payload = {"format": mesh_format, "url": mesh_url, "target_format": target}

        if mesh:
            payload["mesh"] = mesh

        self.output_format = target

        return asyncio.run(self._run_bytes(payload))


def _parse_check(data: dict) -> dict[str, Any]:
    """
    Read the verdict out of a rig-check response, pass or fail.

    A pass carries the rig type in ``output``; a refusal comes back as
    ``status: failed`` with it in ``error.message`` ("model is not riggable,
    rig_type=others"). Both forms are parsed.

    A missing flag reads as not riggable.
    """

    output = data.get("output") or {}
    riggable = bool(output.get("riggable", output.get("is_riggable", False)))
    rig_type = str(output.get("rig_type") or output.get("type") or "")

    if not rig_type:
        message = str((data.get("error") or {}).get("message") or "")
        found = re.search(r"rig_type\s*=\s*([A-Za-z_]+)", message)
        if found:
            rig_type = found.group(1).lower()

    return {
        "riggable": riggable,
        "rig_type": rig_type or "biped",
        # True when the mesh has no recognised body plan, so there is no
        # rig_type to retry with.
        "unclassified": rig_type == UNCLASSIFIED,
        "raw": data,
    }


EXPECTED_LIMBS = {
    "biped": 4,        # two arms, two legs
    "quadruped": 4,
    "hexapod": 6,
    "octopod": 8,
    "avian": 4,        # two wings, two legs
    "serpentine": 0,
    "aquatic": 0,
}


def inspect_rig(glb_bytes: bytes) -> dict[str, Any]:
    """
    Report how much of a rigged GLB's skeleton is anatomically named.

    Two naming schemes come out of this service:

      * generic  — ``tripo::0_Left_Limb_0``, used for quadrupeds, birds and
        anything else described only as numbered limb chains.
      * humanoid — ``L_Thigh``, ``R_Forearm``, ``Spine01``, used for bipeds.

    Anything else (``bone_N``) is structure the rigger did not resolve. A
    preset clip only drives named joints.

    Returns:
        bones (int)         — total joints
        named (int)         — joints carrying a recognised name
        anonymous (int)     — unresolved joints
        limbs (int)         — distinct named limb chains
        limb_names (list)   — e.g. ["0_Left", "0_Right"] or ["L_arm", "R_leg"]
        scheme (str)        — "generic", "humanoid", or "none"
        has_spine (bool), has_head (bool)
    """

    offset, gltf = 12, None
    while offset < len(glb_bytes):
        length, kind = struct.unpack_from("<II", glb_bytes, offset)
        if kind == 0x4E4F534A:
            gltf = json.loads(glb_bytes[offset + 8: offset + 8 + length])
            break
        offset += 8 + length
    empty = {"bones": 0, "named": 0, "anonymous": 0, "limbs": 0,
             "limb_names": [], "scheme": "none",
             "has_spine": False, "has_head": False}
    if gltf is None or not gltf.get("skins"):
        return empty

    nodes = gltf["nodes"]
    joints = gltf["skins"][0]["joints"]
    names = [str(nodes[j].get("name") or "") for j in joints]

    generic = [n for n in names if n.startswith("tripo::")]
    if generic:
        # The trailing index is a segment along one limb, so segments collapse
        # to a chain: 0_Left_Limb_0..2 is one limb, not three.
        chains = set()
        for name in generic:
            match = re.match(r"tripo::(\d+_(?:Left|Right))_Limb_\d+$", name)
            if match:
                chains.add(match.group(1))
        return {
            "bones": len(joints),
            "named": len(generic),
            "anonymous": len(names) - len(generic),
            "limbs": len(chains),
            "limb_names": sorted(chains),
            "scheme": "generic",
            "has_spine": any("Spine" in n for n in generic),
            "has_head": any("Head" in n for n in generic),
        }

    # Humanoid scheme. A limb counts as present when its root bone is there;
    # twist and segment bones hang off those and would inflate the count.
    HUMANOID_LIMB_ROOTS = {
        "L_arm": ("l_upperarm", "leftarm", "l_arm"),
        "R_arm": ("r_upperarm", "rightarm", "r_arm"),
        "L_leg": ("l_thigh", "leftupleg", "l_leg"),
        "R_leg": ("r_thigh", "rightupleg", "r_leg"),
    }
    lowered = [n.lower() for n in names]
    chains = {
        label for label, aliases in HUMANOID_LIMB_ROOTS.items()
        if any(n in aliases for n in lowered)
    }
    if not chains:
        return {**empty, "bones": len(joints), "anonymous": len(names)}

    # Anonymous means unresolved, so `bone_N` and empty names only. Everything
    # else in a humanoid rig is anatomy: hands, toes, twists, clavicles.
    anonymous = sum(1 for n in lowered if not n or re.fullmatch(r"bone_\d+", n))
    return {
        "bones": len(joints),
        "named": len(names) - anonymous,
        "anonymous": anonymous,
        "limbs": len(chains),
        "limb_names": sorted(chains),
        "scheme": "humanoid",
        "has_spine": any("spine" in n or "pelvis" in n for n in lowered),
        "has_head": any("head" in n for n in lowered),
    }


def rig_quality_note(report: dict[str, Any], rig_type: str) -> str:
    """Summarise a rig report in one line."""
    expected = EXPECTED_LIMBS.get(str(rig_type).lower(), 0)
    if report["bones"] == 0:
        return "no skeleton at all"
    parts = [f"{report['bones']} bones",
             f"{report['named']} named", f"{report['anonymous']} anonymous",
             f"{report['limbs']}/{expected} limb chains"]
    if expected and report["limbs"] < expected:
        parts.append(
            "— preset clips will only drive the named chains, so the unnamed "
            "limbs stay in the bind pose"
        )
    return ", ".join(parts[:4]) + ("  " + parts[4] if len(parts) > 4 else "")


FLIPPED_JOINT_DEGREES = 150.0


def inspect_animation(glb_bytes: bytes) -> dict[str, Any]:
    """
    Check an animated GLB for joints the retarget flipped.

    A clip whose first frame sits ~180 deg from a joint's rest orientation has
    been inverted on that joint: the bone points backwards and the skin across
    it shears. The tearing is local to the affected limb.

    Returns:
        clip (str)          — name of the longest clip
        joints (int)        — joints the clip drives
        moving (int)        — joints with more than 5 deg of travel
        flipped (list)      — [(name, degrees), ...] past FLIPPED_JOINT_DEGREES
        worst (float)       — largest first-frame deviation, in degrees
    """

    component = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
                 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
    counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    offset, gltf, binary = 12, None, None
    while offset < len(glb_bytes):
        length, kind = struct.unpack_from("<II", glb_bytes, offset)
        chunk = glb_bytes[offset + 8: offset + 8 + length]
        if kind == 0x4E4F534A:
            gltf = json.loads(chunk)
        elif kind == 0x004E4942:
            binary = chunk
        offset += 8 + length

    empty = {"clip": None, "joints": 0, "moving": 0, "flipped": [], "worst": 0.0}
    if not gltf or not gltf.get("animations") or binary is None:
        return empty

    def read(index):
        acc = gltf["accessors"][index]
        fmt, size = component[acc["componentType"]]
        n = counts[acc["type"]]
        view = gltf["bufferViews"][acc["bufferView"]]
        base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride") or size * n
        return [struct.unpack_from("<" + fmt * n, binary, base + i * stride)
                for i in range(acc["count"])]

    def angle(a, b):
        dot = min(1.0, abs(sum(x * y for x, y in zip(a, b))))
        return math.degrees(2 * math.acos(dot))

    animation = max(gltf["animations"],
                    key=lambda a: len(a.get("channels", [])))
    nodes = gltf["nodes"]
    flipped, worst, moving, seen = [], 0.0, 0, set()

    for channel in animation["channels"]:
        target = channel["target"]
        seen.add(target["node"])
        if target["path"] != "rotation":
            continue
        values = read(animation["samplers"][channel["sampler"]]["output"])
        rest = nodes[target["node"]].get("rotation", [0, 0, 0, 1])
        deviation = angle(values[0], rest)
        worst = max(worst, deviation)
        if max(angle(values[0], v) for v in values) > 5:
            moving += 1
        if deviation >= FLIPPED_JOINT_DEGREES:
            flipped.append((str(nodes[target["node"]].get("name") or "?"),
                            round(deviation, 1)))

    return {
        "clip": animation.get("name"),
        "joints": len(seen),
        "moving": moving,
        "flipped": sorted(flipped, key=lambda item: -item[1]),
        "worst": round(worst, 1),
    }