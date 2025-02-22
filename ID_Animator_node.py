# !/usr/bin/env python
# -*- coding: UTF-8 -*-


import os
import random
import sys
from einops import rearrange
import torchvision
import yaml
import torch
import cv2
from PIL import Image
import numpy as np

from transformers import CLIPTextModel, CLIPTokenizer
from omegaconf import OmegaConf
from safetensors import safe_open
from insightface.app import FaceAnalysis
from insightface.utils import face_align
from diffusers import (AutoencoderKL, DDIMScheduler, ControlNetModel,
                       KDPM2AncestralDiscreteScheduler, LMSDiscreteScheduler,
                       AutoPipelineForInpainting, DPMSolverMultistepScheduler, DPMSolverSinglestepScheduler,
                       EulerDiscreteScheduler, HeunDiscreteScheduler, UNet2DConditionModel,
                       KDPM2DiscreteScheduler,
                       EulerAncestralDiscreteScheduler, UniPCMultistepScheduler,
                       StableDiffusionXLControlNetPipeline, DDPMScheduler, TCDScheduler, LCMScheduler)

from .faceadapter.face_adapter import FaceAdapterPlusForVideoLora
from .animatediff.utils.convert_from_ckpt import convert_ldm_unet_checkpoint, convert_ldm_clip_checkpoint, \
    convert_ldm_vae_checkpoint
from .animatediff.utils.util import load_weights
from .animatediff.pipelines.pipeline_animation import AnimationPipeline
from .animatediff.models.unet import UNet3DConditionModel
from .animatediff.utils.util import save_videos_grid, export_to_video

import folder_paths

dir_path = os.path.dirname(os.path.abspath(__file__))
path_dir = os.path.dirname(dir_path)
file_path = os.path.dirname(path_dir)

motion_path = os.path.join(dir_path, "models","animatediff_models",)
motion_model_list = os.listdir(motion_path)
#print(motion_model_list)

paths = []
for search_path in folder_paths.get_folder_paths("diffusers"):
    if os.path.exists(search_path):
        for root, subdir, files in os.walk(search_path, followlinks=True):
            if "model_index.json" in files:
                paths.append(os.path.relpath(root, start=search_path))

if paths != []:
    paths = ["none"] + [x for x in paths if x]
else:
    paths = ["none", ]

def tensor_to_image(tensor):
    # tensor = tensor.cpu()
    image_np = tensor.squeeze().mul(255).clamp(0, 255).byte().numpy()
    image = Image.fromarray(image_np, mode='RGB')
    return image
def phi2narry(img):
    img = torch.from_numpy(np.array(img).astype(np.float32) / 255.0).unsqueeze(0)
    return img

def narry_list(list_in):
    for i in range(len(list_in)):
        value = list_in[i]
        modified_value = phi2narry(value)
        list_in[i] = modified_value
    return list_in


scheduler_list = [
    "DDIM",
    "DDPM",
    "DPM++ 2M",
    "DPM++ 2M Karras",
    "DPM++ 2M SDE",
    "DPM++ 2M SDE Karras",
    "DPM++ SDE",
    "DPM++ SDE Karras",
    "DPM2",
    "DPM2 Karras",
    "DPM2 a",
    "DPM2 a Karras",
    "Heun",
    "LCM",
    "LMS",
    "LMS Karras",
    "UniPC",
    "UniPC_Bh2",
    "TCD"
]


def get_sheduler(name):
    scheduler = False
    if name == "DDIM":
        scheduler = DDIMScheduler
    elif name == "DDPM":
        scheduler = DDPMScheduler
    elif name == "DPM++ 2M":
        scheduler = DPMSolverMultistepScheduler
    elif name == "DPM++ 2M Karras":
        scheduler = DPMSolverMultistepScheduler(use_karras_sigmas=True)
    elif name == "DPM++ 2M SDE":
        scheduler = DPMSolverMultistepScheduler(algorithm_type="sde-dpmsolver++")
    elif name == "DPM++ 2M SDE Karras":
        scheduler = DPMSolverMultistepScheduler(use_karras_sigmas=True, algorithm_type="sde-dpmsolver++")
    elif name == "DPM++ SDE":
        scheduler = DPMSolverSinglestepScheduler
    elif name == "DPM++ SDE Karras":
        scheduler = DPMSolverSinglestepScheduler(use_karras_sigmas=True)
    elif name == "DPM2":
        scheduler = KDPM2DiscreteScheduler
    elif name == "DPM2 Karras":
        scheduler = KDPM2DiscreteScheduler(use_karras_sigmas=True)
    elif name == "DPM2 a":
        scheduler = KDPM2AncestralDiscreteScheduler
    elif name == "DPM2 a Karras":
        scheduler = KDPM2AncestralDiscreteScheduler(use_karras_sigmas=True)
    elif name == "Heun":
        scheduler = HeunDiscreteScheduler
    elif name == "LCD":
        scheduler = LCMScheduler
    elif name == "LMS":
        scheduler = LMSDiscreteScheduler
    elif name == "LMS Karras":
        scheduler = LMSDiscreteScheduler(use_karras_sigmas=True)
    elif name == "UniPC_Bh1":
        scheduler = UniPCMultistepScheduler(solver_type="bh1")
    elif name == "UniPC_Bh2":
        scheduler = UniPCMultistepScheduler(solver_type="bh2")
    elif name == "TCD":
        scheduler = TCDScheduler
    return scheduler


def get_local_path(file_path, model_path):
    path = os.path.join(file_path, "models", "diffusers", model_path)
    model_path = os.path.normpath(path)
    if sys.platform=='win32':
        model_path = model_path.replace('\\', "/")
    return model_path


def get_instance_path(path):
    os_path = os.path.normpath(path)
    if sys.platform=='win32':
        os_path = os_path.replace('\\', "/")
    return os_path


class ID_Animator:

    def __init__(self):
        pass
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "repo_id": ("STRING", {"forceInput": True}),
                "prompt": ("STRING", {"multiline": True,
                                      "default": "Iron Man soars through the clouds, his repulsors blazing"}),
                "negative_prompt": ("STRING", {"multiline": True,
                                               "default": "semi-realistic, cgi, 3d, render, sketch, cartoon,"
                                                          " drawing, anime, text, close up, cropped, out of frame,"
                                                          " worst quality, low quality, jpeg artifacts, ugly, duplicate,"
                                                          " morbid, mutilated, extra fingers, mutated hands, poorly drawn hands,"
                                                          " poorly drawn face, mutation, deformed, blurry, dehydrated, bad anatomy, "
                                                          "bad proportions, extra limbs, cloned face, disfigured, gross proportions,"
                                                          " malformed limbs, missing arms, missing legs, extra arms, extra legs, fused fingers,"
                                                          " too many fingers, long neck"}),
                "scheduler": (scheduler_list,),
                "steps": ("INT", {"default": 30, "min": 1, "max": 2048, "step": 1, "display": "number"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "cfg": ("FLOAT", {"default": 8, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
                "height": ("INT", {"default": 512, "min": 64, "max": 8192, "step": 64, "display": "number"}),
                "width": ("INT", {"default": 512, "min": 64, "max": 8192, "step": 64, "display": "number"}),
                "video_length": ("INT", {"default": 16, "min": 1, "max": 100}),
                "scale": ("FLOAT", {"default": 0.8, "min": 0.1, "max": 10.0, "step": 0.1, "round": 0.01}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "id_animator"
    CATEGORY = "ID_Animator"

    def load_model(self, inference_config, sd_version, scheduler, id_ckpt, image_encoder_path, dreambooth_model_path,
                   motion_module_path):

        inference_config = OmegaConf.load(inference_config)

        tokenizer = CLIPTokenizer.from_pretrained(sd_version, subfolder="tokenizer", torch_dtype=torch.float16,
                                                  )
        text_encoder = CLIPTextModel.from_pretrained(sd_version, subfolder="text_encoder", torch_dtype=torch.float16,
                                                     ).cuda()
        vae = AutoencoderKL.from_pretrained(sd_version, subfolder="vae", torch_dtype=torch.float16,
                                            ).cuda()
        unet = UNet3DConditionModel.from_pretrained_2d(sd_version, subfolder="unet",
                                                       unet_additional_kwargs=OmegaConf.to_container(
                                                           inference_config.unet_additional_kwargs)
                                                       ).cuda()
        scheduler_used = get_sheduler(scheduler)
        pipeline = AnimationPipeline(
            vae=vae, text_encoder=text_encoder, tokenizer=tokenizer, unet=unet,
            controlnet=None,
            # beta_start=0.00085, beta_end=0.012, beta_schedule="linear",steps_offset=1
            scheduler=scheduler_used(**OmegaConf.to_container(inference_config.noise_scheduler_kwargs)
                                     # scheduler=EulerAncestralDiscreteScheduler(**OmegaConf.to_container(inference_config.noise_scheduler_kwargs)
                                     # scheduler=EulerAncestralDiscreteScheduler(beta_start=0.00085, beta_end=0.012, beta_schedule="linear",steps_offset=1

                                     ), torch_dtype=torch.float16,
        ).to("cuda")

        pipeline = load_weights(
            pipeline,
            # motion module
            motion_module_path=motion_module_path,
            motion_module_lora_configs=[],
            # domain adapter
            adapter_lora_path="",
            adapter_lora_scale=1,
            # image layers
            dreambooth_model_path=None,
            lora_model_path="",
            lora_alpha=0.8
        ).to("cuda")
        if dreambooth_model_path != "":
            print(f"load dreambooth model from {dreambooth_model_path}")
            dreambooth_state_dict = {}
            with safe_open(dreambooth_model_path, framework="pt", device="cpu") as f:
                for key in f.keys():
                    dreambooth_state_dict[key] = f.get_tensor(key)

                converted_vae_checkpoint = convert_ldm_vae_checkpoint(dreambooth_state_dict, pipeline.vae.config)
                # print(vae)
                # vae ->to_q,to_k,to_v
                # print(converted_vae_checkpoint)
                convert_vae_keys = list(converted_vae_checkpoint.keys())
                for key in convert_vae_keys:
                    if "encoder.mid_block.attentions" in key or "decoder.mid_block.attentions" in key:
                        new_key = None
                        if "key" in key:
                            new_key = key.replace("key", "to_k")
                        elif "query" in key:
                            new_key = key.replace("query", "to_q")
                        elif "value" in key:
                            new_key = key.replace("value", "to_v")
                        elif "proj_attn" in key:
                            new_key = key.replace("proj_attn", "to_out.0")
                        if new_key:
                            converted_vae_checkpoint[new_key] = converted_vae_checkpoint.pop(key)

                pipeline.vae.load_state_dict(converted_vae_checkpoint)

                converted_unet_checkpoint = convert_ldm_unet_checkpoint(dreambooth_state_dict, pipeline.unet.config)
                pipeline.unet.load_state_dict(converted_unet_checkpoint, strict=False)

                pipeline.text_encoder = convert_ldm_clip_checkpoint(dreambooth_state_dict).to("cuda")
            del dreambooth_state_dict
            pipeline = pipeline.to(torch.float16)
            id_animator = FaceAdapterPlusForVideoLora(pipeline, image_encoder_path, id_ckpt, num_tokens=16,
                                                      device=torch.device("cuda"), torch_type=torch.float16)
            return id_animator

    def get_video_img(self,videos,rescale=False, n_rows=6):
        videos = rearrange(videos, "b c t h w -> t b c h w")
        outputs = []
        for x in videos:
            x = torchvision.utils.make_grid(x, nrow=n_rows)
            x = x.transpose(0, 1).transpose(1, 2).squeeze(-1)
            if rescale:
                x = (x + 1.0) / 2.0  # -1,1 -> 0,1
            x=tensor_to_image(x)
            outputs.append(x)
        return outputs


    def id_animator(self, image, repo_id,prompt, negative_prompt, scheduler
                    ,steps,seed, cfg, height, width, video_length,scale):
        repo_id,dreambooth_model_path,motion_models=repo_id.split(",",2)
        inference_config = get_instance_path(os.path.join(dir_path,"inference-v2.yaml"))
        id_ckpt = get_instance_path(os.path.join(dir_path, "models", "animator.ckpt"))
        image_encoder_path = get_instance_path(os.path.join(dir_path, "models","image_encoder"))
        app = FaceAnalysis(name="buffalo_l", providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        app.prepare(ctx_id=0, det_size=(320, 320))

        animator = self.load_model(inference_config, repo_id, scheduler, id_ckpt, image_encoder_path,
                                   dreambooth_model_path, motion_models)

        Pil_img = tensor_to_image(image)
        img = cv2.cvtColor(np.asarray(Pil_img), cv2.COLOR_RGB2BGR)
        faces = app.get(img)
        face_roi = face_align.norm_crop(img, faces[0]['kps'], 112)
        face_roi = cv2.cvtColor(face_roi, cv2.COLOR_BGR2RGB)
        pil_image = [Image.fromarray(face_roi).resize((224, 224))]
        sample = animator.generate(pil_image, negative_prompt=negative_prompt, prompt=prompt, num_inference_steps=steps,
                                   seed=seed,
                                   guidance_scale=cfg,
                                   width=width,
                                   height=height,
                                   video_length=video_length,
                                   scale=scale,
                                   )

        gen =self.get_video_img(sample)  # 获取生成动画单帧的pli列表
        gen =narry_list(gen) # 列表排序
        images = torch.from_numpy(np.fromiter(gen, np.dtype((np.float32, (height, width, 3))))) # numpy
        return (images,)

class ID_Repo_Choice:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "local_model_path": (paths,),
                "repo_id": ("STRING", {"default": "runwayml/stable-diffusion-v1-5"}),
                "ckpt_name": (folder_paths.get_filename_list("checkpoints"),),
                "motion_model": (["none"]+motion_model_list,)
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("repo_id",)
    FUNCTION = "repo_choice"
    CATEGORY = "ID_Animator"

    def repo_choice(self, local_model_path, repo_id,ckpt_name,motion_model):
        if repo_id == "":
            if local_model_path == "none":
                raise "you need fill repo_id or download model in diffusers directory "
            elif local_model_path != "none":
                model_path = get_local_path(file_path, local_model_path)
                repo_id = get_instance_path(model_path)
        elif repo_id != "" and repo_id.find("/") == -1:
            raise "Incorrect repo_id format"
        elif repo_id != "" and repo_id.find("\\") != -1:
            repo_id = get_instance_path(repo_id)
        if motion_model =="none":
            raise "you need download motion model in animatediff_models directory "
        ckpt_path = get_instance_path(folder_paths.get_full_path("checkpoints", ckpt_name))
        motion_path = get_instance_path(os.path.join(dir_path, "models", "animatediff_models", motion_model))
        repo_id=repo_id +","+ ckpt_path +","+ motion_path
        return (repo_id,)


NODE_CLASS_MAPPINGS = {
    "ID_Animator": ID_Animator,
    "ID_Repo_Choice":ID_Repo_Choice
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ID_Animator": "ID_Animator",
    "ID_Repo_Choice":"ID_Repo_Choice"
}
