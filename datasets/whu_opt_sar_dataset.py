from transform import *
import os
import os.path as osp
import numpy as np
import torch
from torch.utils.data import Dataset
import cv2
import matplotlib.pyplot as plt
import albumentations as albu
import matplotlib.patches as mpatches
from PIL import Image, ImageOps
import random


CLASSES = ('background', 'farmland', 'city', 'village', 'water', 'forest', 'road', 'others')

PALETTE = [[0, 0, 0], [204, 102, 0], [255, 0, 0], [255, 255, 0],
           [0, 0, 255], [85, 166, 0], [152, 102, 153]]


ORIGIN_IMG_SIZE = (640, 640)
INPUT_IMG_SIZE = (640, 640)
TEST_IMG_SIZE = (640, 640)
def get_training_transform():
    train_transform = [
        # albu.RandomBrightnessContrast(brightness_limit=0.25, contrast_limit=0.25, p=0.15),
        # albu.RandomRotate90(p=0.25),
        albu.Normalize()
    ]
    return albu.Compose(train_transform)


def train_aug(img, sar, mask):
    # multi-scale training and crop
    crop_aug = Compose([RandomScale(scale_list=[0.75, 1.0, 1.25, 1.5], mode='value'),
                        SmartCropV1(crop_size=512, max_ratio=0.75, ignore_index=255, nopad=False)])
    img, sar, mask = crop_aug(img, sar, mask)

    img, sar, mask = np.array(img), np.array(sar), np.array(mask)
    aug = get_training_transform()(image=img.copy(), sar=sar.copy(), mask=mask.copy())
    img, sar, mask = aug['image'], aug['sar'], aug['mask']
    return img, sar, mask


def get_val_transform():
    val_transform = [
        albu.Normalize()
    ]
    return albu.Compose(val_transform)


def val_aug(img, sar, mask):
    img, sar, mask = np.array(img), sar.array(sar), np.array(mask)
    aug = get_val_transform()(image=img.copy(), mask=mask.copy())
    img, mask = aug['image'], aug['mask']
    aug_sar = get_val_transform()(image=sar.copy())
    sar = aug_sar['image']
    return img, sar, mask


class WhuOPTSARDataset(Dataset):
    def __init__(self, data_root=r'D:\yaogan\GeoSeg-main\GeoSeg-main\data\whu-opt-sar\train',
                 rgb_dir='optical',
                 sar_dir='sar',
                 mosaic_ratio=0.0,
                 mask_dir='lbl',
                 suffix='.tif',
                 transform=train_aug, img_size=ORIGIN_IMG_SIZE):
        self.data_root = data_root
        self.rgb_dir = rgb_dir
        self.mask_dir = mask_dir
        self.sar_dir = sar_dir
        self.mosaic_ratio = mosaic_ratio

        self.suffix = suffix
        self.transform = transform
        self.img_size = img_size
        self.img_ids = self.get_img_ids(self.data_root, self.rgb_dir, self.sar_dir, self.mask_dir)

    def __getitem__(self, index):
        p_ratio = random.random()
        img, sar, mask = self.load_img_and_mask(index)
        if p_ratio < self.mosaic_ratio:
            img, sar, mask = self.load_mosaic_img_and_mask(index)
        if self.transform:
            img, sar, mask = self.transform(img, sar, mask)
        img = torch.from_numpy(img).permute(2, 0, 1).float()
        sar = torch.from_numpy(sar).long()
        mask = torch.from_numpy(mask).long()
        img_id, img_type = self.img_ids[index]
        results = {'img': img, 'sar': sar, 'gt_semantic_seg': mask, 'img_id': img_id}

        return results

    def __len__(self):
        length = len(self.img_ids)
        return length

    def get_img_ids(self, data_root, img_dir, sar_dir, mask_dir):
        opt_filename_list = os.listdir(osp.join(data_root, img_dir))
        sar_filename_list = os.listdir(osp.join(data_root, sar_dir))
        mask_filename_list = os.listdir(osp.join(data_root, mask_dir))

        assert len(opt_filename_list) == len(mask_filename_list) == len(sar_filename_list)
        img_ids = [(str(id.split('.')[0])) for id in opt_filename_list]
        img_ids = img_ids

        return img_ids

    def load_img_and_mask(self, index):
        img_id, img_type = self.img_ids[index]
        img_name = osp.join(self.data_root, img_type, self.rgb_dir, img_id + self.suffix)
        sar_name = osp.join(self.data_root, img_type, self.sar_dir, img_id + self.suffix)
        mask_name = osp.join(self.data_root, img_type, self.mask_dir, img_id + self.suffix)
        img = Image.open(img_name).convert('RGB')
        sar = Image.open(sar_name).convert('L')
        mask = Image.open(mask_name).convert('L')

        return img, sar, mask

    def load_mosaic_img_and_mask(self, index):
        indexes = [index] + [random.randint(0, len(self.img_ids) - 1) for _ in range(3)]
        img_a, sar_a, mask_a = self.load_img_and_mask(indexes[0])
        img_b, sar_b, mask_b = self.load_img_and_mask(indexes[1])
        img_c, sar_c, mask_c = self.load_img_and_mask(indexes[2])
        img_d, sar_d, mask_d = self.load_img_and_mask(indexes[3])

        img_a, sar_a, mask_a = np.array(img_a), np.array(sar_a), np.array(mask_a)
        img_b, sar_b, mask_b = np.array(img_b), np.array(sar_b), np.array(mask_b)
        img_c, sar_c, mask_c = np.array(img_c), np.array(sar_c), np.array(mask_c)
        img_d, sar_d, mask_d = np.array(img_d), np.array(sar_d), np.array(mask_d)

        w = self.img_size[1]
        h = self.img_size[0]

        start_x = w // 4
        strat_y = h // 4
        # The coordinates of the splice center
        offset_x = random.randint(start_x, (w - start_x))
        offset_y = random.randint(strat_y, (h - strat_y))

        crop_size_a = (offset_x, offset_y)
        crop_size_b = (w - offset_x, offset_y)
        crop_size_c = (offset_x, h - offset_y)
        crop_size_d = (w - offset_x, h - offset_y)

        random_crop_a = albu.RandomCrop(width=crop_size_a[0], height=crop_size_a[1])
        random_crop_b = albu.RandomCrop(width=crop_size_b[0], height=crop_size_b[1])
        random_crop_c = albu.RandomCrop(width=crop_size_c[0], height=crop_size_c[1])
        random_crop_d = albu.RandomCrop(width=crop_size_d[0], height=crop_size_d[1])

        croped_a = random_crop_a(image=img_a.copy(), sar=sar_a.copy(), mask=mask_a.copy())
        croped_b = random_crop_b(image=img_b.copy(), sar=sar_b.copy(), mask=mask_b.copy())
        croped_c = random_crop_c(image=img_c.copy(), sar=sar_c.copy(), mask=mask_c.copy())
        croped_d = random_crop_d(image=img_d.copy(), sar=sar_d.copy(), mask=mask_d.copy())

        img_crop_a, sar_crop_a, mask_crop_a = croped_a['image'], croped_a['sar'], croped_a['mask']
        img_crop_b, sar_crop_b, mask_crop_b = croped_b['image'], croped_b['sar'], croped_b['mask']
        img_crop_c, sar_crop_c, mask_crop_c = croped_c['image'], croped_c['sar'], croped_c['mask']
        img_crop_d, sar_crop_d, mask_crop_d = croped_d['image'], croped_d['sar'], croped_d['mask']

        img_top = np.concatenate((img_crop_a, img_crop_b), axis=1)
        img_bottom = np.concatenate((img_crop_c, img_crop_d), axis=1)
        img = np.concatenate((img_top, img_bottom), axis=0)

        sar_top = np.concatenate((sar_crop_a, sar_crop_b), axis=1)
        sar_bottom = np.concatenate((sar_crop_c, sar_crop_d), axis=1)
        sar = np.concatenate((sar_top, sar_bottom), axis=0)

        top_mask = np.concatenate((mask_crop_a, mask_crop_b), axis=1)
        bottom_mask = np.concatenate((mask_crop_c, mask_crop_d), axis=1)
        mask = np.concatenate((top_mask, bottom_mask), axis=0)
        mask = np.ascontiguousarray(mask)
        img = np.ascontiguousarray(img)
        sar = np.ascontiguousarray(sar)

        img = Image.fromarray(img)
        sar = Image.fromarray(sar)
        mask = Image.fromarray(mask)

        return img, sar, mask


WhuOPTSAR_val_dataset = WhuOPTSARDataset(data_root=r'D:\yaogan\GeoSeg-main\GeoSeg-main\data\whu-opt-sar\train',
                                        mosaic_ratio=0.0,
                                        transform=val_aug)


class LoveDATestDataset(Dataset):
    def __init__(self, data_root='data/LoveDA/Test', img_dir='images_png',
                 img_suffix='.png',  mosaic_ratio=0.0,
                 img_size=ORIGIN_IMG_SIZE):
        self.data_root = data_root
        self.img_dir = img_dir

        self.img_suffix = img_suffix
        self.mosaic_ratio = mosaic_ratio
        self.img_size = img_size
        self.img_ids = self.get_img_ids(self.data_root, self.img_dir)

    def __getitem__(self, index):
        img = self.load_img(index)

        img = np.array(img)
        aug = albu.Normalize()(image=img)
        img = aug['image']

        img = torch.from_numpy(img).permute(2, 0, 1).float()
        img_id, img_type = self.img_ids[index]

        results = {'img': img, 'img_id': img_id, 'img_type': img_type}

        return results

    def __len__(self):
        length = len(self.img_ids)

        return length

    def get_img_ids(self, data_root, img_dir):
        urban_img_filename_list = os.listdir(osp.join(data_root, 'Urban', img_dir))
        urban_img_ids = [(str(id.split('.')[0]), 'Urban') for id in urban_img_filename_list]
        rural_img_filename_list = os.listdir(osp.join(data_root, 'Rural', img_dir))
        rural_img_ids = [(str(id.split('.')[0]), 'Rural') for id in rural_img_filename_list]
        img_ids = urban_img_ids + rural_img_ids

        return img_ids

    def load_img(self, index):
        img_id, img_type = self.img_ids[index]
        img_name = osp.join(self.data_root, img_type, self.img_dir, img_id + self.img_suffix)
        img = Image.open(img_name).convert('RGB')

        return img


def show_img_mask_seg(seg_path, img_path, mask_path, start_seg_index):
    seg_list = os.listdir(seg_path)
    fig, ax = plt.subplots(2, 3, figsize=(18, 12))
    seg_list = seg_list[start_seg_index:start_seg_index+2]
    patches = [mpatches.Patch(color=np.array(PALETTE[i])/255., label=CLASSES[i]) for i in range(len(CLASSES))]
    for i in range(len(seg_list)):
        seg_id = seg_list[i]
        img_seg = cv2.imread(f'{seg_path}/{seg_id}', cv2.IMREAD_UNCHANGED)
        img_seg = img_seg.astype(np.uint8)
        img_seg = Image.fromarray(img_seg).convert('P')
        img_seg.putpalette(np.array(PALETTE, dtype=np.uint8))
        img_seg = np.array(img_seg.convert('RGB'))
        mask = cv2.imread(f'{mask_path}/{seg_id}', cv2.IMREAD_UNCHANGED)
        mask = mask.astype(np.uint8)
        mask = Image.fromarray(mask).convert('P')
        mask.putpalette(np.array(PALETTE, dtype=np.uint8))
        mask = np.array(mask.convert('RGB'))
        img_id = str(seg_id.split('.')[0])+'.tif'
        img = cv2.imread(f'{img_path}/{img_id}', cv2.IMREAD_COLOR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        ax[i, 0].set_axis_off()
        ax[i, 0].imshow(img)
        ax[i, 0].set_title('RS IMAGE ' + img_id)
        ax[i, 1].set_axis_off()
        ax[i, 1].imshow(mask)
        ax[i, 1].set_title('Mask True ' + seg_id)
        ax[i, 2].set_axis_off()
        ax[i, 2].imshow(img_seg)
        ax[i, 2].set_title('Mask Predict ' + seg_id)
        ax[i, 2].legend(handles=patches, bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0., fontsize='large')


def show_seg(seg_path, img_path, start_seg_index):
    seg_list = os.listdir(seg_path)
    fig, ax = plt.subplots(2, 2, figsize=(12, 12))
    seg_list = seg_list[start_seg_index:start_seg_index+2]
    patches = [mpatches.Patch(color=np.array(PALETTE[i])/255., label=CLASSES[i]) for i in range(len(CLASSES))]
    for i in range(len(seg_list)):
        seg_id = seg_list[i]
        img_seg = cv2.imread(f'{seg_path}/{seg_id}', cv2.IMREAD_UNCHANGED)
        img_seg = img_seg.astype(np.uint8)
        img_seg = Image.fromarray(img_seg).convert('P')
        img_seg.putpalette(np.array(PALETTE, dtype=np.uint8))
        img_seg = np.array(img_seg.convert('RGB'))
        img_id = str(seg_id.split('.')[0])+'.tif'
        img = cv2.imread(f'{img_path}/{img_id}', cv2.IMREAD_COLOR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        ax[i, 0].set_axis_off()
        ax[i, 0].imshow(img)
        ax[i, 0].set_title('RS IMAGE '+img_id)
        ax[i, 1].set_axis_off()
        ax[i, 1].imshow(img_seg)
        ax[i, 1].set_title('Seg IMAGE '+seg_id)
        ax[i, 1].legend(handles=patches, bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0., fontsize='large')


def show_mask(img, mask, img_id):
    fig, (ax1, ax2) = plt.subplots(nrows=1, ncols=2, figsize=(12, 12))
    patches = [mpatches.Patch(color=np.array(PALETTE[i])/255., label=CLASSES[i]) for i in range(len(CLASSES))]
    mask = mask.astype(np.uint8)
    mask = Image.fromarray(mask).convert('P')
    mask.putpalette(np.array(PALETTE, dtype=np.uint8))
    mask = np.array(mask.convert('RGB'))
    ax1.imshow(img)
    ax1.set_title('RS IMAGE ' + str(img_id)+'.png')
    ax2.imshow(mask)
    ax2.set_title('Mask ' + str(img_id)+'.png')
    ax2.legend(handles=patches, bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0., fontsize='large')