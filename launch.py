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
deadline = min(time.time() + int(os.environ.get("RUN_SECONDS") or "540"), float(os.environ.get("UNTIL") or "1e12"))
while time.time() < deadline:
    for ocpu, mem in ((2, 12), (1, 6)):
        for ad in ("jGHu:US-ASHBURN-AD-1", "jGHu:US-ASHBURN-AD-2", "jGHu:US-ASHBURN-AD-3"):
            time.sleep(20)
            try:
                r = c.launch_instance(oci.core.models.LaunchInstanceDetails(
                    compartment_id=T, availability_domain=ad, shape="VM.Standard.A1.Flex", display_name="stovima-backend",
                    shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=ocpu, memory_in_gbs=mem),
                    source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=img, boot_volume_size_in_gbs=50),
                    create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=os.environ["OCI_SUBNET"], assign_public_ip=True),
                    metadata={"ssh_authorized_keys": open("stovima_oracle.pub").read().strip()}))
                print("LAUNCHED", ad, ocpu, mem, r.data.id); open("launched", "w").write(r.data.id); sys.exit(0)
            except oci.exceptions.ServiceError as e:
                print(ad, ocpu, e.status, e.code, (e.message or "")[:80])
    print("round done: no capacity"); time.sleep(30)
print("no capacity")
