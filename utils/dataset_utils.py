import shapely.wkt
import geopandas as gpd
import numpy as np
import pandas as pd
import ast
from operator import itemgetter


def get_matrix_mapping(args):
    tessellation = pd.read_csv(args.path+f'/data/Tessellation_{args.tile_size}m_'+args.city+'.csv')
    tessellation['geometry'] = [shapely.wkt.loads(el) for el in tessellation.geometry]
    tessellation = gpd.GeoDataFrame(tessellation, geometry='geometry')

    # list_positions = [np.array(el) for el in tessellation['position']]
    # list_positions = np.array(sorted(list_positions,key=itemgetter(1)))
    list_positions = [np.array(ast.literal_eval(el)) for el in tessellation['position']]
    list_positions = np.array(sorted(np.array(list_positions), key=itemgetter(1)))

    max_x = list_positions[:, 0].max()
    max_y = list_positions[:, 1].max()

    pos_set = set()
    new_value = max_y +1
    for i, pos in enumerate(list_positions[:, 1]):
        if pos not in pos_set:
            new_value -= 1
            pos_set.add(pos)
        list_positions[i, 1] = new_value

    tessellation['positions'] = list(sorted(list_positions, key=itemgetter(0)))

    matrix_mapping = {el[0]:el[1] for el in zip(tessellation['tile_ID'], tessellation['positions'])}
    y_max = np.array(list(tessellation['positions']))[:,1].max()+1
    x_max = np.array(list(tessellation['positions']))[:,0].max()+1

    return matrix_mapping, x_max, y_max


def restore_od_matrix(od_matrix, empty_indices):
        for idx in empty_indices:
            od_matrix = np.insert(od_matrix, idx, np.zeros([od_matrix.shape[0], od_matrix.shape[1], od_matrix.shape[3]]), 2)
            od_matrix = np.insert(od_matrix, idx, np.zeros([od_matrix.shape[0], od_matrix.shape[1], od_matrix.shape[2]]), 3)
        return od_matrix


def od_matrix_to_map(od_matrix, mapping, min_tile_id, map_shape):
    map_matrix = np.zeros(map_shape)
    for i in range(od_matrix.shape[2]): # origin
        for j in range(od_matrix.shape[3]): # destination
            x, y = mapping[j+min_tile_id]
            map_matrix[:, int(x), int(y), 0, :] += od_matrix[:, :, i, j]#.numpy() # Inflow
            x, y = mapping[i+min_tile_id]
            map_matrix[:, int(x), int(y), 1, :] += od_matrix[:, :, i, j]#.numpy() # Outflow
    return map_matrix


def remove_empty_rows(X_dataset, flows):
    X_new = []
    X_sum = []
    for i in range(flows):
        X_new.append(X_dataset[:,:,:,i])
        X_sum.append(np.add.reduce(X_new[i]))

        X_new[i] = X_new[i][:,~(X_sum[i]==0).all(1)]    # Removing empty rows
        X_new[i] = X_new[i][:,:,~(X_sum[i].T==0).all(1)]    # Removing empty columns

    X_dataset = np.empty([X_dataset.shape[0], X_new[0].shape[1], X_new[0].shape[2], flows])

    for i in range(flows):
        X_dataset[:,:,:,i] = X_new[i]

    return X_dataset, (~(X_sum[i]==0).all(1), ~(X_sum[i].T==0).all(1))


def to_2D_map(actual, predicted, matrix_mapping, min_tile_id, x_max, y_max, args):

    actual_map = od_matrix_to_map(actual, matrix_mapping, min_tile_id, [actual.shape[0], x_max, y_max, 2, 1])
    predicted_map = od_matrix_to_map(predicted, matrix_mapping, min_tile_id, [predicted.shape[0], x_max, y_max, 2, 1])

    # Removing rows and columns with no flows
    actual_map, non_empty_shape = remove_empty_rows(actual_map[:,:,:,:,0], 2)
    predicted_map = predicted_map[:, non_empty_shape[0], :, :, :]
    predicted_map = predicted_map[:, :, non_empty_shape[1], :, :]
    predicted_map = predicted_map[:, :, :, :, 0]

    return actual_map, predicted_map