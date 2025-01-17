import tensorflow as tf
import cv2
from pixel2mesh.models import GCN
from pixel2mesh.fetcher import *

# Set random seed
seed = 1024
np.random.seed(seed)
tf.set_random_seed(seed)

# Settings
flags = tf.app.flags
FLAGS = flags.FLAGS
flags.DEFINE_string(
    'data_list', 'pixel2mesh/utils/train_list_new.txt', 'Data list path.')
flags.DEFINE_float('learning_rate', 3e-5, 'Initial learning rate.')
flags.DEFINE_integer('epochs', 30, 'Number of epochs to train.')
flags.DEFINE_integer('hidden', 192, 'Number of units in  hidden layer.')
flags.DEFINE_integer(
    'feat_dim', 963, 'Number of units in perceptual feature layer.')
flags.DEFINE_integer('coord_dim', 3, 'Number of units in output layer.')
flags.DEFINE_float('weight_decay', 5e-6, 'Weight decay for L2 loss.')

# Define placeholders(dict) and model
num_blocks = 3
num_supports = 2
placeholders = {
    # initial 3D coordinates
    'features': tf.placeholder(tf.float32, shape=(None, 3)),
    # input image to network
    'img_inp': tf.placeholder(tf.float32, shape=(224, 224, 3)),
    # ground truth (point cloud with vertex normal)
    'labels': tf.placeholder(tf.float32, shape=(None, 6)),
    # graph structure in the first block
    'support1': [tf.sparse_placeholder(tf.float32) for _ in range(num_supports)],
    # graph structure in the second block
    'support2': [tf.sparse_placeholder(tf.float32) for _ in range(num_supports)],
    # graph structure in the third block
    'support3': [tf.sparse_placeholder(tf.float32) for _ in range(num_supports)],
    # helper for face loss (not used)
    'faces': [tf.placeholder(tf.int32, shape=(None, 4)) for _ in range(num_blocks)],
    # helper for normal loss
    'edges': [tf.placeholder(tf.int32, shape=(None, 2)) for _ in range(num_blocks)],
    # helper for laplacian regularization
    'lape_idx': [tf.placeholder(tf.int32, shape=(None, 10)) for _ in range(num_blocks)],
    # helper for graph unpooling
    'pool_idx': [tf.placeholder(tf.int32, shape=(None, 2)) for _ in range(num_blocks-1)]
}
model = GCN(placeholders, logging=True)

# Construct feed dictionary


def construct_feed_dict(pkl, placeholders):
    coord = pkl[0]
    pool_idx = pkl[4]
    faces = pkl[5]
    lape_idx = pkl[7]
    edges = []
    for i in range(1, 4):
        adj = pkl[i][1]
        edges.append(adj[0])

    feed_dict = dict()
    feed_dict.update({placeholders['features']: coord})
    feed_dict.update({placeholders['edges'][i]: edges[i]
                      for i in range(len(edges))})
    feed_dict.update({placeholders['faces'][i]: faces[i]
                      for i in range(len(faces))})
    feed_dict.update({placeholders['pool_idx'][i]: pool_idx[i]
                      for i in range(len(pool_idx))})
    feed_dict.update({placeholders['lape_idx'][i]: lape_idx[i]
                      for i in range(len(lape_idx))})
    feed_dict.update({placeholders['support1'][i]: pkl[1][i]
                      for i in range(len(pkl[1]))})
    feed_dict.update({placeholders['support2'][i]: pkl[2][i]
                      for i in range(len(pkl[2]))})
    feed_dict.update({placeholders['support3'][i]: pkl[3][i]
                      for i in range(len(pkl[3]))})
    return feed_dict

# Tensorboard Initialization
scalar_summary = tf.summary.scalar
histogram_summary = tf.summary.histogram
merge_summary = tf.summary.merge
SummaryWriter = tf.summary.FileWriter

# Introduce Tensorboard Variable
loss_smry = scalar_summary('loss', model.loss)

# Load data
data = DataFetcher(FLAGS.data_list)
data.setDaemon(True)
data.start()  # To initiate the threads
train_number = data.number

# Initialize session
config = tf.ConfigProto()
config.gpu_options.allow_growth = False
config.allow_soft_placement = True
sess = tf.Session(config=config)
sess.run(tf.global_variables_initializer())
model.load(sess)
writer = SummaryWriter('./graphs', tf.get_default_graph())

# Construct feed dictionary
pkl = pickle.load(open('./Debugging/pixel2mesh/help/initGraph.dat', 'rb'))
feed_dict = construct_feed_dict(pkl, placeholders)

# Train model
train_loss = open('pixel2mesh/utils/record_training_loss.log', 'a')
train_loss.write('Start training, lr =  %f\n' % (FLAGS.learning_rate))

counter = 0
for epoch in range(FLAGS.epochs):
    all_loss = np.zeros(train_number, dtype='float32')
    for iters in range(train_number):
        # Fetch training data
        img_inp, y_train, data_id = data.fetch()
        feed_dict.update({placeholders['img_inp']: img_inp})
        feed_dict.update({placeholders['labels']: y_train})

        # Training step
        # output1, output1_2 = sess.run(
        #     [model.output1, model.output1_2], feed_dict=feed_dict)
        loss_smry_, _, dists, out1, out2, out3 = sess.run(
            [loss_smry, model.opt_op, model.loss, model.output1, model.output2, model.output3], feed_dict=feed_dict)
        all_loss[iters] = dists
        mean_loss = np.mean(all_loss[np.where(all_loss)])

        if (iters+1) % 2 == 0:
            print 'Epoch %d, Iteration %d' % (epoch + 1, iters + 1)
            print 'Mean loss = %f, iter loss = %f, %d' % (
                mean_loss, dists, data.queue.qsize())

        # Save summary
        writer.add_summary(loss_smry_, counter)
        counter += 1
    # Save model
    model.save(sess)
    train_loss.write('Epoch %d, loss %f\n' % (epoch+1, mean_loss))
    train_loss.flush()

writer.close()
data.shutdown()
print 'Training Finished!'
