import os
import shutil
import logging as log
import warnings

import numpy as np

from .base import Callback


class ModelCheckpoint(Callback):
    r"""
    Save the model after every epoch.

    Args:
        filepath: path to save the model file.
            Can contain named formatting options to be auto-filled.

            Example::

                # save epoch and val_loss in name
                ModelCheckpoint(filepath='{epoch:02d}-{val_loss:.2f}.hdf5')
                # saves file like: /path/epoch_2-val_loss_0.2.hdf5
        monitor (str): quantity to monitor.
        verbose (bool): verbosity mode, False or True.
        save_top_k (int): if `save_top_k == k`,
            the best k models according to
            the quantity monitored will be saved.
            if ``save_top_k == 0``, no models are saved.
            if ``save_top_k == -1``, all models are saved.
            Please note that the monitors are checked every `period` epochs.
            if ``save_top_k >= 2`` and the callback is called multiple
            times inside an epoch, the name of the saved file will be
            appended with a version count starting with `v0`.
        mode (str): one of {auto, min, max}.
            If ``save_top_k != 0``, the decision
            to overwrite the current save file is made
            based on either the maximization or the
            minimization of the monitored quantity. For `val_acc`,
            this should be `max`, for `val_loss` this should
            be `min`, etc. In `auto` mode, the direction is
            automatically inferred from the name of the monitored quantity.
        save_weights_only (bool): if True, then only the model's weights will be
            saved (`model.save_weights(filepath)`), else the full model
            is saved (`model.save(filepath)`).
        period (int): Interval (number of epochs) between checkpoints.

    Example::

        from pytorch_lightning import Trainer
        from pytorch_lightning.callbacks import ModelCheckpoint

        # saves checkpoints to my_path whenever 'val_loss' has a new min
        checkpoint_callback = ModelCheckpoint(filepath='my_path')
        Trainer(checkpoint_callback=checkpoint_callback)
    """

    def __init__(self, filepath, monitor: str = 'val_loss', verbose: bool = False,
                 save_top_k: int = 1, save_weights_only: bool = False,
                 mode: str = 'auto', period: int = 1, prefix: str = ''):
        super().__init__()
        if save_top_k and os.path.isdir(filepath) and len(os.listdir(filepath)) > 0:
            warnings.warn(
                f"Checkpoint directory {filepath} exists and is not empty with save_top_k != 0."
                "All files in this directory will be deleted when a checkpoint is saved!"
            )

        self.monitor = monitor
        self.verbose = verbose
        self.filepath = filepath
        os.makedirs(filepath, exist_ok=True)
        self.save_top_k = save_top_k
        self.save_weights_only = save_weights_only
        self.period = period
        self.epochs_since_last_check = 0
        self.prefix = prefix
        self.best_k_models = {}
        # {filename: monitor}
        self.kth_best_model = ''
        self.best = 0
        self.save_function = None

        mode_dict = {
            'min': (np.less, np.Inf, 'min'),
            'max': (np.greater, -np.Inf, 'max'),
            'auto': (np.greater, -np.Inf, 'max') if 'acc' in self.monitor or self.monitor.startswith('fmeasure')
            else (np.less, np.Inf, 'min'),
        }

        if mode not in mode_dict:
            warnings.warn(
                f'ModelCheckpoint mode {mode} is unknown, '
                'fallback to auto mode.', RuntimeWarning)
            mode = 'auto'

        self.monitor_op, self.kth_value, self.mode = mode_dict[mode]

    def _del_model(self, filepath):
        try:
            shutil.rmtree(filepath)
        except OSError:
            os.remove(filepath)

    def _save_model(self, filepath):
        # make paths
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # delegate the saving to the model
        if self.save_function is not None:
            self.save_function(filepath)
        else:
            raise ValueError(".save_function() not set")

    def check_monitor_top_k(self, current):
        less_than_k_models = len(self.best_k_models) < self.save_top_k
        if less_than_k_models:
            return True
        return self.monitor_op(current, self.best_k_models[self.kth_best_model])

    def on_validation_end(self, trainer, pl_module):
        logs = trainer.callback_metrics
        epoch = trainer.current_epoch
        self.epochs_since_last_check += 1

        if self.save_top_k == 0:
            # no models are saved
            return
        if self.epochs_since_last_check >= self.period:
            self.epochs_since_last_check = 0
            filepath = f'{self.filepath}/{self.prefix}_ckpt_epoch_{epoch}.ckpt'
            version_cnt = 0
            while os.path.isfile(filepath):
                # this epoch called before
                filepath = f'{self.filepath}/{self.prefix}_ckpt_epoch_{epoch}_v{version_cnt}.ckpt'
                version_cnt += 1

            if self.save_top_k != -1:
                current = logs.get(self.monitor)

                if current is None:
                    warnings.warn(
                        f'Can save best model only with {self.monitor} available,'
                        ' skipping.', RuntimeWarning)
                else:
                    if self.check_monitor_top_k(current):
                        self._do_check_save(filepath, current, epoch)
                    else:
                        if self.verbose > 0:
                            log.info(
                                f'\nEpoch {epoch:05d}: {self.monitor}'
                                f' was not in top {self.save_top_k}')

            else:
                if self.verbose > 0:
                    log.info(f'\nEpoch {epoch:05d}: saving model to {filepath}')
                self._save_model(filepath)

    def _do_check_save(self, filepath, current, epoch):
        # remove kth
        if len(self.best_k_models) == self.save_top_k:
            delpath = self.kth_best_model
            self.best_k_models.pop(self.kth_best_model)
            self._del_model(delpath)

        self.best_k_models[filepath] = current
        if len(self.best_k_models) == self.save_top_k:
            # monitor dict has reached k elements
            _op = max if self.mode == 'min' else min
            self.kth_best_model = _op(self.best_k_models,
                                      key=self.best_k_models.get)
            self.kth_value = self.best_k_models[self.kth_best_model]

        _op = min if self.mode == 'min' else max
        self.best = _op(self.best_k_models.values())

        if self.verbose > 0:
            log.info(
                f'\nEpoch {epoch:05d}: {self.monitor} reached'
                f' {current:0.5f} (best {self.best:0.5f}), saving model to'
                f' {filepath} as top {self.save_top_k}')
        self._save_model(filepath)
