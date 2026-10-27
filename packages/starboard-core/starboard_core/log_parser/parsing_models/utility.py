# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
from typing import Any


def db_to_aws_configs(appobj: Any) -> dict[str, Any]:
    meta = appobj.sparkMetadata
    rt = "spark.databricks.clusterUsageTags."

    config = {
        "clusterConf": {
            "AvailabilityZone": meta[rt + "containerZoneId"],
            "InstanceGroupType": {
                "MASTER": {
                    "InstanceType": meta[rt + "driverNodeType"],
                    "InstanceCount": 1,
                    "TotalEBSSizePerInstance": 0,
                    "VolumesPerInstance": 1,
                },
                "CORE": {
                    "InstanceType": meta[rt + "clusterNodeType"],
                    "InstanceCount": int(meta[rt + "clusterWorkers"]),
                    "TotalEBSSizePerInstance": int(meta[rt + "clusterEbsVolumeCount"])
                    * int(meta[rt + "clusterEbsVolumeSize"]),
                    "VolumesPerInstance": int(meta[rt + "clusterEbsVolumeCount"]),
                },
                "TASK": {
                    "InstanceType": None,
                    "InstanceCount": None,
                    "TotalEBSSizePerInstance": None,
                    "VolumesPerInstance": None,
                },
            },
        },
        "region": meta[rt + "dataPlaneRegion"],
        "type": "INSTANCE_GROUP",
    }

    return config
