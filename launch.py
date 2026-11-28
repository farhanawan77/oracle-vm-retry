"""Tries to launch the free A1 VM once per shape/AD. Exit 0 = launched or already exists."""
import os, sys, time, oci

cfg = {"user": os.environ["OCI_USER"], "tenancy": os.environ["OCI_TENANCY"],
       "fingerprint": os.environ["OCI_FINGERPRINT"], "key_file": "key.pem", "region": "us-ashburn-1"}
T = cfg["tenancy"]
c = oci.core.ComputeClient(cfg)

live = [i for i in c.list_instances(T, display_name="stovima-backend").data
        if i.lifecycle_state not in ("TERMINATED", "TERMINATING")]
if live:
    print("ALREADY", live[0].id); open("launched", "w").write(live[0].id); sys.exit(0)

img = c.list_images(T, operating_system="Canonical Ubuntu", operating_system_version="24.04",
                    shape="VM.Standard.A1.Flex", sort_by="TIMECREATED", sort_order="DESC", limit=1).data[0].id
# Fallback: one free AMD micro (1 OCPU / 1GB), kept separately; ARM tries continue.
MICRO = "VM.Standard.E2.1.Micro"
def has(name):
    return any(i.lifecycle_state not in ("TERMINATED", "TERMINATING")
               for i in c.list_instances(T, display_name=name).data)
# Always Free allows two AMD micros; keep trying until both exist.
MICRO_NAMES = ["stovima-micro", "stovima-micro-2"]
micro_todo = [n for n in MICRO_NAMES if not has(n)]
micro_done = not micro_todo
micro_img = c.list_images(T, operating_system="Canonical Ubuntu", operating_system_version="24.04",
                          shape=MICRO, sort_by="TIMECREATED", sort_order="DESC", limit=1).data[0].id
# The free micro is allowed in one AD only; others answer LimitExceeded.
micro_ads = ["jGHu:US-ASHBURN-AD-1", "jGHu:US-ASHBURN-AD-2", "jGHu:US-ASHBURN-AD-3"]
def try_micro():
    global micro_done
    for ad in list(micro_ads):
        time.sleep(10)
        try:
            r = c.launch_instance(oci.core.models.LaunchInstanceDetails(
                compartment_id=T, availability_domain=ad, shape=MICRO, display_name=micro_todo[0],
                source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=micro_img, boot_volume_size_in_gbs=50),
                create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=os.environ["OCI_SUBNET"], assign_public_ip=True),
                metadata={"ssh_authorized_keys": open("stovima_oracle.pub").read().strip()}))
            print("MICRO LAUNCHED", micro_todo[0], ad, r.data.id)
            micro_todo.pop(0); micro_done = not micro_todo; return
        except oci.exceptions.ServiceError as e:
            print("micro", ad, e.status, e.code, (e.message or "")[:80])
            if e.code == "LimitExceeded":
                micro_ads.remove(ad)
                if not micro_ads: micro_done = True; return
            if e.status == 429: time.sleep(60)

deadline = min(time.time() + int(os.environ.get("RUN_SECONDS") or "540"), float(os.environ.get("UNTIL") or "1e12"))
ADS = ("jGHu:US-ASHBURN-AD-1", "jGHu:US-ASHBURN-AD-2", "jGHu:US-ASHBURN-AD-3")
SIZES = ((4, 24), (2, 12), (1, 6))  # biggest free size first
M = oci.core.models

def launch(ad, ocpu, mem):
    r = c.launch_instance(M.LaunchInstanceDetails(
        compartment_id=T, availability_domain=ad, shape="VM.Standard.A1.Flex", display_name="stovima-backend",
        shape_config=M.LaunchInstanceShapeConfigDetails(ocpus=ocpu, memory_in_gbs=mem),
        source_details=M.InstanceSourceViaImageDetails(image_id=img, boot_volume_size_in_gbs=50),
        create_vnic_details=M.CreateVnicDetails(subnet_id=os.environ["OCI_SUBNET"], assign_public_ip=True),
        metadata={"ssh_authorized_keys": open("stovima_oracle.pub").read().strip()}))
    print("LAUNCHED", ad, ocpu, mem, r.data.id); open("launched", "w").write(r.data.id); sys.exit(0)

def available(ad):
    """Sizes Oracle reports free in this AD right now (capacity report, no launch)."""
    r = c.create_compute_capacity_report(M.CreateComputeCapacityReportDetails(
        compartment_id=T, availability_domain=ad,
        shape_availabilities=[M.CreateCapacityReportShapeAvailabilityDetails(
            instance_shape="VM.Standard.A1.Flex",
            instance_shape_config=M.CapacityReportInstanceShapeConfig(ocpus=o, memory_in_gbs=m)) for o, m in SIZES]))
    return [(int(s.instance_shape_config.ocpus), int(s.instance_shape_config.memory_in_gbs))
            for s in r.data.shape_availabilities if s.availability_status == "AVAILABLE"]

rnd = 0
while time.time() < deadline:
    rnd += 1
    if not micro_done: try_micro()
    # Fast path: ask where capacity is, launch there at once (biggest size first).
    for ad in ADS:
        time.sleep(3)
        try:
            for ocpu, mem in available(ad):
                try:
                    launch(ad, ocpu, mem)
                except oci.exceptions.ServiceError as e:
                    print("report said free but", ad, ocpu, e.status, e.code, (e.message or "")[:80])
                    if e.status == 429: time.sleep(60)
        except oci.exceptions.ServiceError as e:
            print("report", ad, e.status, e.code)
            if e.status == 429: time.sleep(60)
    # The report can lag: every 10th round still try a blind launch.
    if rnd % 3 == 0:
        for ocpu, mem in ((2, 12), (1, 6)):
            for ad in ADS:
                time.sleep(10)
                try:
                    launch(ad, ocpu, mem)
                except oci.exceptions.ServiceError as e:
                    print(ad, ocpu, e.status, e.code, (e.message or "")[:80])
                    if e.status == 429: time.sleep(60)
        print("round", rnd, "done: no capacity")
print("no capacity")
