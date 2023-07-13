from exp.exp_basic import Exp_Basic
from data_provider.data_factory import data_provider
from model import GTFormer, CrowdNet
from utils.dataset_utils import restore_od_matrix, get_matrix_mapping, to_2D_map
from utils.exp_utils import EarlyStopping

import os
import torch
import torch.nn as nn
import time
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error


class Exp_Main(Exp_Basic):
    def __init__(self, args):
        super(Exp_Main, self).__init__(args)

    def _build_model(self):
        model_dict = {
            'GTFormer': GTFormer,
            'CrowdNet': CrowdNet,
        }
        model = model_dict[self.args.model].Model(self.args).float()

        return model


    def train(self):
        train_loader, _, _, _, key_indices = data_provider('train', self.args)

        path = os.path.join(self.args.path + f'/checkpoints_{self.args.model}/')
        if not os.path.exists(path):
            os.makedirs(path)

        train_steps = len(train_loader)
        early_stopping = EarlyStopping(patience=self.args.patience, verbose=True)

        model_optim = torch.optim.Adam(self.model.parameters(), lr=self.args.lr)
        criterion = nn.MSELoss()
        my_lr_scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer=model_optim, gamma=0.96)

        for epoch in range(self.args.train_epochs):
            iter_count = 0
            train_loss = []

            self.model.train()
            epoch_time = time.time()
            for i, (batch_x, batch_y) in enumerate(train_loader):
                iter_count += 1
                model_optim.zero_grad()
                batch_x = batch_x.float().to(self.device)
                batch_y = batch_y.float().to(self.device)

                outputs, _, _ = self.model(batch_x, key_indices)

                loss = criterion(outputs, batch_y)
                train_loss.append(loss.item())

                loss.backward()
                model_optim.step()

            train_loss = np.average(train_loss)
            vali_loss = self.vali()

            my_lr_scheduler.step()
            print("Epoch: {}, cost time: {}, Steps: {} | Train Loss: {} Vali Loss: {}".format(
                epoch + 1, time.time()-epoch_time, train_steps, train_loss, vali_loss))
            early_stopping(vali_loss, self.model, path)
            if early_stopping.early_stop:
                print("Early stopping")
                break

        best_model_path = path + 'checkpoint.pth'
        self.model.load_state_dict(torch.load(best_model_path))

        return


    def vali(self):
        vali_loader, _, _, _, key_indices = data_provider('val', self.args)
        total_loss = []
        criterion = nn.MSELoss()
        self.model.eval()

        with torch.no_grad():
            for i, (batch_x, batch_y) in enumerate(vali_loader):
                batch_x = batch_x.float().to(self.device)
                batch_y = batch_y.float().to(self.device)

                outputs, _, _ = self.model(batch_x, key_indices)

                loss = criterion(outputs, batch_y)

                total_loss.append(loss.item())
        total_loss = np.average(total_loss)
        self.model.train()
        return total_loss

    def test(self, itr):
        test_loader, empty_indices, min_tile_id, tile_index, key_indices = data_provider('test', self.args)

        self.model.load_state_dict(torch.load(os.path.join(self.args.path + f'/checkpoints_{self.args.model}/' + 'checkpoint.pth')))

        preds = []
        trues = []

        self.model.eval()


        with torch.no_grad():
            for i, (batch_x, batch_y) in enumerate(test_loader):
                batch_x = batch_x.float().to(self.device)
                batch_y = batch_y.float().to(self.device)

                outputs, A_temporal, A_spatial = self.model(batch_x, key_indices)

                preds.append(outputs.cpu().detach().numpy())
                trues.append(batch_y.cpu().detach().numpy())

                if self.args.save_output:
                  A_spatial_ = torch.zeros((self.args.batch_size, self.args.n_head, self.args.num_tiles**2, self.args.num_tiles**2)).to(self.device)
                  for j in range(self.args.num_tiles**4):
                      A_spatial_[:, :, j, key_indices[j]] = A_spatial[:, :, j, :]


        preds = np.concatenate(preds, axis=0)
        trues = np.concatenate(trues, axis=0)

        crowd_rmse_test = np.sqrt(mean_squared_error(trues.flatten().reshape(-1,1), preds.flatten().reshape(-1,1)))
        crowd_mae_test = mean_absolute_error(trues.flatten().reshape(-1,1), preds.flatten().reshape(-1,1))

        print('Crowd Flow Prediction')
        print("RMSE Error test: ", crowd_rmse_test)
        print("MAE Error test: ", crowd_mae_test)

        matrix_mapping, x_max, y_max = get_matrix_mapping(self.args)
        trues = restore_od_matrix(trues, empty_indices)
        preds = restore_od_matrix(preds, empty_indices)

        actual_map, predicted_map = to_2D_map(trues, preds, matrix_mapping, min_tile_id, x_max, y_max, self.args)

        inout_rmse_test = np.sqrt(mean_squared_error(actual_map.flatten().reshape(-1,1), predicted_map.flatten().reshape(-1,1)))
        inout_mae_test = mean_absolute_error(actual_map.flatten().reshape(-1,1), predicted_map.flatten().reshape(-1,1))

        print('In-Out Flow Prediction')
        print("RMSE Error test: ", inout_rmse_test)
        print("MAE Error test: ", inout_mae_test)

        save_path = os.path.join(self.args.path + '/results_data/' + f'{self.args.tile_size}m_{self.args.sample_time}_{self.args.model}')
        if not os.path.exists(save_path):
          os.makedirs(save_path)
        f = open(save_path + '/result.txt', 'a')
        f.write('itr:{} \n'.format(itr+1))
        f.write('Crowd flow prediction:   mse:{}, mae:{} \n'.format(crowd_rmse_test, crowd_mae_test))
        f.write('In-Out flow prediction:   mse:{}, mae:{} \n'.format(inout_rmse_test, inout_mae_test))
        f.write('\n')
        f.write('\n')
        f.close()

        if self.args.save_output:
          if not os.path.exists(save_path + f'/{itr}'):
              os.makedirs(save_path + f'/{itr}')
          np.save(save_path + f'/{itr}/' + 'preds.npy', preds)
          np.save(save_path + f'/{itr}/' + 'trues.npy', trues)
          np.save(save_path + f'/{itr}/' + 'A_temporal.npy', A_temporal.cpu().detach().numpy())
          np.save(save_path + f'/{itr}/' + 'A_spatial.npy', A_spatial_.cpu().detach().numpy())
          np.save(save_path + f'/{itr}/' + 'tile_index.npy', tile_index)

        return