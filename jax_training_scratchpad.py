from keras_core import operations as ops
from keras_core import backend
from keras_core.optimizers import SGD
from keras_core.layers.layer import Layer
from keras_core import initializers
import jax
from jax import numpy as jnp
import numpy as np


class MiniDense(Layer):
    def __init__(self, units, name=None):
        super().__init__(name=name)
        self.units = units

    def build(self, input_shape):
        input_dim = input_shape[-1]
        w_shape = (input_dim, self.units)
        w_value = initializers.GlorotUniform()(w_shape)
        self.w = backend.Variable(w_value)

        b_shape = (self.units,)
        b_value = initializers.Zeros()(b_shape)
        self.b = backend.Variable(b_value)

    def call(self, inputs):
        return ops.matmul(inputs, self.w) + self.b


class MiniDropout(Layer):
    def __init__(self, rate, name=None):
        super().__init__(name=name)
        self.rate = rate
        self.seed_generator = backend.random.RandomSeedGenerator(1337)

    def call(self, inputs):
        return backend.random.dropout(inputs, self.rate, seed=self.seed_generator)


class MiniBatchNorm(Layer):
    def __init__(self, name=None):
        super().__init__(name=name)
        self.epsilon = 1e-5
        self.momentum = 0.99

    def build(self, input_shape):
        shape = (input_shape[-1],)
        self.mean = backend.Variable(initializers.Zeros()(shape), trainable=False)
        self.variance = backend.Variable(
            initializers.GlorotUniform()(shape), trainable=False
        )
        self.beta = backend.Variable(initializers.Zeros()(shape))
        self.gamma = backend.Variable(initializers.Ones()(shape))

    def call(self, inputs, training=False):
        if training:
            mean = jnp.mean(inputs, axis=(0,))  # TODO: extend to rank 3+
            variance = jnp.var(inputs, axis=(0,))
            outputs = (inputs - mean) / (variance + self.epsilon)
            self.variance.assign(
                self.variance * self.momentum + variance * (1.0 - self.momentum)
            )
            self.mean.assign(self.mean * self.momentum + mean * (1.0 - self.momentum))
        else:
            outputs = (inputs - self.mean) / (self.variance + self.epsilon)
        outputs *= self.gamma
        outputs += self.beta
        return outputs


class MyModel(Layer):
    def __init__(self, units, num_classes):
        super().__init__()
        self.dense1 = MiniDense(units)
        self.bn = MiniBatchNorm()
        self.dropout = MiniDropout(0.5)
        self.dense2 = MiniDense(num_classes)

    def call(self, x):
        x = self.dense1(x)
        x = self.bn(x)
        x = self.dropout(x)
        return self.dense2(x)


# class Optimizer:
#     @property
#     def variables(self):
#         return []

#     def build(self, variables):
#         pass

#     def stateless_apply_gradients(self, vars_and_grads, optimizer_variables):
#         new_values = []
#         for v, g in vars_and_grads:
#             new_v = v - g * 0.001
#             new_values.append(new_v)
#         return new_values, optimizer_variables


def Dataset():
    for _ in range(10):
        yield (np.random.random((8, 4)), np.random.random((8, 2)))


def loss_fn(y_true, y_pred):
    return ops.sum((y_true - y_pred) ** 2)


optimizer = SGD()
model = MyModel(8, 2)
dataset = Dataset()

# Build model
x = ops.convert_to_tensor(np.random.random((8, 4)))
model(x)
# Build optimizer
optimizer.build(model.trainable_variables)


################################
## Currently achievable workflow


def compute_loss_and_updates(trainable_variables, non_trainable_variables, x, y):
    y_pred, non_trainable_variables = model.stateless_call(
        trainable_variables, non_trainable_variables, x
    )
    loss = loss_fn(y, y_pred)
    return loss, non_trainable_variables


grad_fn = jax.value_and_grad(compute_loss_and_updates, has_aux=True)


@jax.jit
def train_step(trainable_variables, non_trainable_variables, optimizer_variables, x, y):
    (loss, non_trainable_variables), grads = grad_fn(
        trainable_variables, non_trainable_variables, x, y
    )
    trainable_variables, optimizer_variables = optimizer.stateless_apply(
        grads, optimizer_variables
    )
    return trainable_variables, non_trainable_variables, optimizer_variables


# Training loop
trainable_variables = model.trainable_variables
non_trainable_variables = model.non_trainable_variables
optimizer_variables = optimizer.variables
for x, y in dataset:
    trainable_variables, non_trainable_variables, optimizer_variables = train_step(
        trainable_variables, non_trainable_variables, optimizer_variables, x, y
    )

# Post-processing model state update
for variable, value in zip(model.trainable_variables, trainable_variables):
    variable.assign(value)
for variable, value in zip(model.non_trainable_variables, non_trainable_variables):
    variable.assign(value)


print("Updated values")


# ####################
# ## Alternative workflow


# def compute_loss_and_updates(trainable_variables, non_trainable_variables, x, y):
#     y_pred, updates = model.stateless_call(
#         trainable_variables, non_trainable_variables, x
#     )
#     loss = loss_fn(y, y_pred)
#     return loss, updates


# grad_fn = jax.value_and_grad(compute_loss_and_updates, has_aux=True)


# @jax.jit
# def train_step(trainable_variables, non_trainable_variables, x, y):
#     (loss, updates), grads = grad_fn(trainable_variables, non_trainable_variables, x, y)
#     updates += optimizer.get_updates(zip(trainable_variables, grads))
#     return updates


# trainable_variables = model.trainable_variables
# non_trainable_variables = model.non_trainable_variables

# for x, y in dataset:
#     updates = train_step(trainable_variables, non_trainable_variables, x, y)
#     for variable, value in updates:
#         variable.assign(value)