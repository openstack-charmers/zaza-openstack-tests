"""Module containing Kubernetes related utilities."""
import asyncio

import zaza


WRITE_POD = """
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {0}-pvc
  annotations:
   volume.beta.kubernetes.io/storage-class: {0}
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
---
kind: Pod
apiVersion: v1
metadata:
  name: {0}-write-test
spec:
  volumes:
  - name: shared-data
    persistentVolumeClaim:
      claimName: {0}-pvc
      readOnly: false
  containers:
    - name: {0}-write-test
      image: ubuntu
      command: ["/bin/bash", "-c", "echo 'JUJU TEST' > /data/juju"]
      volumeMounts:
      - name: shared-data
        mountPath: /data
  restartPolicy: Never
"""

READ_POD = """
kind: Pod
apiVersion: v1
metadata:
  name: {0}-read-test
spec:
  volumes:
  - name: shared-data
    persistentVolumeClaim:
      claimName: {0}-pvc
      readOnly: false
  containers:
    - name: {0}-read-test
      image: ubuntu
      command: ["/bin/bash", "-c", "cat /data/juju"]
      volumeMounts:
      - name: shared-data
        mountPath: /data
  restartPolicy: Never
"""


async def async_kubectl(cmd):
    cmd = "/snap/bin/kubectl {}".format(cmd)
    result = await zaza.model.async_run_on_leader("kubernetes-master", cmd)
    assert result["Code"] == 0, "'kubectl {}' failed ({}): {}".format(
        cmd, result["Code"], result["Stderr"],
    )
    return result["Stdout"]


kubectl = zaza.sync_wrapper(async_kubectl)


async def async_wait_for_pod_complete(pod_name):
    for attempt in range(6):
        pod_status = await async_kubectl("get pod {}".format(pod_name))
        if "Completed" in pod_status:
            break
        else:
            await asyncio.sleep(10)
    else:
        raise zaza.model.ModelTimeout("Timed out waiting for Kubernetes "
                                      "pod {} to complete".format(pod_name))


wait_for_pod_complete = zaza.sync_wrapper(async_wait_for_pod_complete)


def validate_storage_class(sc_name):
    """Validate the given SC can be written to and read from."""

    write_pod_name = "{}-write-test".format(sc_name)
    read_pod_name = "{}-read-pod-test".format(sc_name)

    storage_classes = kubectl("get sc")
    assert sc_name in storage_classes, ("Storage class {} not found in "
                                        "{}".format(sc_name, storage_classes))

    kubectl("create -f - << EOF{}EOF".format(WRITE_POD.format(sc_name)))
    wait_for_pod_complete(write_pod_name)

    kubectl("create -f - << EOF{}EOF".format(READ_POD.format(sc_name)))
    wait_for_pod_complete(read_pod_name)

    read_output = kubectl("logs {}".format(read_pod_name))
    assert "JUJU TEST" in read_output, ("Expected output 'JUJU TEST' not "
                                        "found in: {}".format(read_output))

    kubectl("delete pod {} {}".format(read_pod_name, write_pod_name))
    kubectl("delete pvc {}-pvc".format(sc_name))
