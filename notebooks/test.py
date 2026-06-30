# %%
%load_ext autoreload
%autoreload 2

# # %%
# from pathlib import Path
# from hashlib import sha256,sha512

# import hashlib
# import mmap

# f = r"D:\NextCloud\bachelor\data\sample_laz\avt_sample_2.laz"
# f = r"C:\data\13_Pielach\12_PROCESSED_DATASETS\2024-10-09\pielach_2024-10-09.laz"
# p = Path(f)
# if not p.exists and p.is_file:
#     raise ValueError("Path doesnt exist or is not a file")
# stat = p.stat()
# stat.st_mtime; stat.st_size


# def calculate_sha256_mmap(filename):
#     hash_object = hashlib.sha256()
#     with open(filename, 'rb') as f:
#         with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
#             hash_object.update(mm)
#     return hash_object.hexdigest()

# print(calculate_sha256_mmap(f))
# # %%
# import sys
# sys.path.insert(0,"../")
# from stac.catalog.extract import file_meta
# meta = file_meta("../TODO.txt")
# print(meta)

# # # %%
# # from opals import Info
# # inf = Info.Info(r"-inf D:\NextCloud\bachelor\data\sample_laz\avt_sample.laz -exact 1")
# # inf.run()
# # # %%
# # stats = inf.statistic[0]

# # %%
# import sys; sys.path.insert(0,"../")
# from stac.core import config as cfg
# from stac.core.registry import STEM_PATTERNS, LABELS
# from pathlib import Path

# cfg.register_defaults("stem_patterns", STEM_PATTERNS)
# cfg.load_config(Path(r"../configs/sample_campaign.yaml"))
# # cfg.generate_template_config("stem_patterns", Path(r"./sampletestidk.yaml"))
# stems = cfg.section("stem_patterns")
# # %%
# for k,v in stems.items():
#     print(f"{k}:\t{v}\n\n")
